"""Pure CP128 terms and forecast arithmetic; all I/O stays in the existing controller.

The controller context preserves existing validation/mock seams during the bounded
source split; live external execution must pin this module transitively.
"""

# Exact39235028468 diagnostic only. These are retained evidence hashes, not
# authority to query. Keep this in the already pinned revision module.
READ392_SCHEMA = "a1-native-drive-read-39235028468-v1"
READ392_V2_SCHEMA = "a1-native-drive-read-39235028468-v2"
READ392_V3_SCHEMA = "a1-native-drive-read-39235028468-v3"
READ392_V2_DEPLOYMENT_PR = 650
# Actual immutable publication, not a forecast or a new execution window.
READ392_V3_ORIGIN = dict(pull_request=650,
    reviewed_head="e15290fe117c2f62993a742d9a769dcda8f50265",
    source_sha="33c276e06a4bdf26acb15c26d14d68ccb3f165ac",
    tree_sha="07402a43ea79feef3287aaec560e418f7172bacd",
    merged_at_utc="2026-10-20T09:59:28Z")
# Direct user decision retained in the existing Work A preparation packet.
# This is execution-scope evidence, not supplier rights or a runtime grant.
READ392_V2_AUTHORITY = "e6eeea2b9cd592d1edee7694f38dbd9f352f9e7c47e1a3fffa680d256cda1958"
READ392_V2_INPUT = "b36152639bf4c64780c74beba1aeb48aacac4e7d9fba8ecdae77ed4b3c6a9329"
READ392_TASK = "R1000-A1-DRIVE-READ39235028468"
READ392_AUTH = "2a1339c50cad5971d4ea06d9a01d430e9ea28a5f22a1c6b031b79e6aab52a02e"
READ392_CP = "56fbaa42a0627f747f742920697f24ae281fd468109324c95e7eb2634b810a04"
READ392_CP_ID_SHA = "ea714ebd8f194d8c11b6462ff9dd8a4d63d0f942704adb0ab61d76093bbd80dd"
READ392_METER = "0bb8ddf3efe3148a701071b3192afc519957c0af85bb7b02fcf092f7eabccbc0"
READ392_COHORT = "87460c6bbe0269ca1bf12b7d5ee35742d7b6228a93e9b9a560fea4f4484c4cc8"
READ392_FAMILY = "2b6ad59834b498d0935d3284404a5c74e1789a2497813452d80116e90cfe4ea0"
READ392_WINDOW = ("2026-10-19T10:07:57Z","2026-10-19T10:15:00Z")
READ392_USED = dict(provider_gets=968,drive_requests=9847,drive_bytes=1657932691,storage_bytes=131488371)
READ392_ALLOWANCE = dict(provider_gets=0,drive_requests=16,drive_bytes=16000000,storage_bytes=0)
READ392_FIELDS = "nextPageToken,files(id,name,size,parents,createdTime)"
READ392_CHECK_FIELDS = "id,mimeType,trashed,shared,parents,permissions(id,type,role)"
READ392_META_FIELDS = READ392_CHECK_FIELDS+",name,size,createdTime"
# Existing protected gate bytes at reviewed base3c6c216; never infer new trust
# from the candidate HEAD or update the protected gate/runner to satisfy this.
READ392_GATE_PINS={
    ".github/workflows/review_complete_gate.yml":"58494e4941c3bc2084229df5ae239d28889e9385a07989a215813e442e9ced23",
    "tools/check_pr_review_complete.py":"583f1056460ac29ca27cdeb7d8fab9524d9b354ab2de4ca64427544177262ae2"}


def named_read_version(control):
    return {READ392_SCHEMA:1,READ392_V2_SCHEMA:2,READ392_V3_SCHEMA:3}.get(control.get("schema"),0)


def named_read_window(c,control):
    if control.get("schema")==READ392_SCHEMA:
        return VALIDITY_START,VALIDITY_END
    version=named_read_version(control)
    c.require(version in (2,3),"NAMED_READ_AUTH")
    deployment=control.get("deployment")
    c.require(isinstance(deployment,dict) and type(deployment.get("pull_request")) is int
        and (deployment["pull_request"]==READ392_V2_DEPLOYMENT_PR if version==2 else
            deployment["pull_request"]>READ392_V3_ORIGIN["pull_request"]
            and c.encoded(control.get("window_origin"))==c.encoded(READ392_V3_ORIGIN)),"NAMED_READ_DEPLOYMENT_SCOPE")
    window=control.get("deployment_window")
    c.require(isinstance(window,dict) and set(window)=={"deployed_at_utc","expires_at_utc"}
        and all(isinstance(window[k],str) for k in window),"NAMED_READ_DEPLOYMENT_WINDOW")
    start,end=c.utc(window["deployed_at_utc"]),c.utc(window["expires_at_utc"])
    c.require(start>=c.utc(READ392_WINDOW[1]) and end-start==c.timedelta(seconds=86400),
              "NAMED_READ_DEPLOYMENT_WINDOW")
    if version==3:
        c.require(window["deployed_at_utc"]==READ392_V3_ORIGIN["merged_at_utc"],
                  "NAMED_READ_DEPLOYMENT_WINDOW")
    return window["deployed_at_utc"],window["expires_at_utc"]


def named_read_control(c,value,*,accounting=False):
    version=named_read_version(value) if isinstance(value,dict) else 0
    successor=version>=2
    c.require(isinstance(value,dict) and set(value)=={
        "schema","task_key","authorization","expected_master","code_pins_sha256","nonce",
        "checkpoint_file_id","grant_reference","human_authority_sha256","deployment"}
        | ({"deployment_window"} if successor else set())
        | ({"window_origin"} if version==3 else set()),
        "NAMED_READ_CONTROL")
    c.require(version in (1,2,3) and value["task_key"]==READ392_TASK
        and c.validate_authorization(value["authorization"])==READ392_AUTH,"NAMED_READ_AUTH")
    for key,length in (("expected_master",40),("human_authority_sha256",64)):
        c.require(isinstance(value[key],str) and c.re.fullmatch("[0-9a-f]{"+str(length)+"}",value[key]),
                  "NAMED_READ_CONTROL")
    c.require(value["human_authority_sha256"] not in {VALIDITY_AUTHORITY,"0"*64}
        and c.re.fullmatch(c.PREFIX+r"[0-9a-f]{24}",value["nonce"] or "")
        and c.re.fullmatch(r"[A-Za-z0-9_-]{10,100}",value["checkpoint_file_id"] or "")
        and c.digest(value["checkpoint_file_id"].encode())==READ392_CP_ID_SHA
        and c.re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",
                          value["grant_reference"] or "")
        and isinstance(value["code_pins_sha256"],str)
        and c.re.fullmatch(r"[0-9a-f]{64}",value["code_pins_sha256"]),
        "NAMED_READ_AUTHORITY_UNSET")
    deployment=value["deployment"]
    c.require(isinstance(deployment,dict) and set(deployment)=={"pull_request","reviewed_head"}
        and type(deployment["pull_request"]) is int and deployment["pull_request"]>0
        and isinstance(deployment["reviewed_head"],str)
        and c.re.fullmatch(r"[0-9a-f]{40}",deployment["reviewed_head"]),"NAMED_READ_DEPLOYMENT")
    if successor:
        c.require(value["human_authority_sha256"]==READ392_V2_AUTHORITY,"NAMED_READ_AUTHORITY_UNSET")
    start,end=named_read_window(c,value)
    if not accounting:
        c.require(max(c.utc(start),c.utc(READ392_WINDOW[1]))<=c.utc()<c.utc(end),"CAMPAIGN_EXPIRED")
    return value["authorization"]


def named_read_terms(c,control):
    auth=control["authorization"]
    private=dict(root=auth["private_root_folder_id"],folder=auth["private_data_folder_id"],
                 checkpoint=control["checkpoint_file_id"])
    version=named_read_version(control);successor=version>=2
    start,end=named_read_window(c,control)
    result=dict(schema="a1-named-read39235028468-grant-v"+str(version),task_key=READ392_TASK,
        source_sha=control["expected_master"],code_pins_sha256=control["code_pins_sha256"],
        deployment=control["deployment"],nonce=control["nonce"],
        human_authority_sha256=control["human_authority_sha256"],
        validity_authority_sha256=READ392_V2_AUTHORITY if successor else VALIDITY_AUTHORITY,
        not_before_utc=start,expires_at_utc=end,
        failed_run_id=39235028468,failed_run_attempt=1,failed_meter_sha256=READ392_METER,
        capture_auth_sha256=READ392_AUTH,checkpoint_sha256=READ392_CP,checkpoint_bytes=5005,examined=296,
        private_bindings_sha256=c.digest(c.encoded(private)),owner_sha256=c.CONTINUATION["bindings"]["owner_sha256"],
        inventory_window=list(READ392_WINDOW),positive_page_size=2,inventory_page_size=8,pages_per_query=1,
        max_candidate_media=1,candidate_media_limit=434796,candidate_size_is_heuristic=True,
        allowance=dict(READ392_ALLOWANCE),active_seconds_reservation=900,dispatch_reservation=1,
        usage_before=dict(READ392_USED),active_seconds_before=8736,dispatches_before=29,
        original17_tail=c.CONTINUATION["event"],cohort48_tail=READ392_COHORT,family75_tail=READ392_FAMILY,
        unknown_storage_still_charged=[302101,434796],past_diagnostics="UNKNOWN_NOT_ZERO",
        total_platform_cost_verified=False,absence_proven=False,failed_request_body_hash_known=False,
        capture_authorized=False,drive_data_write_authorized=False,failed_post_retry_authorized=False,
        source_admission=False,pit_verified=False,economic_authority=False,budget_reset=False)
    if successor:
        result.update(window_basis="ACTUAL_PROTECTED_PR_MERGED_AT_PLUS_86400_SECONDS",
            next_collection_priority_input_sha256=READ392_V2_INPUT,
            price_capture_requires_separate_typed_continuation=True)
    if version==3:
        result["window_origin"]=dict(control["window_origin"])
    return result


def named_read_proof(c,control,*,accounting=False):
    named_read_control(c,control,accounting=accounting)
    comment_id=int(control["grant_reference"].rsplit("-",1)[1])
    comment=c.gh_json(f"repos/{c.REPO}/issues/comments/{comment_id}")
    version=named_read_version(control);successor=version>=2
    terms,proof=human_record(c,comment,
        "A1_SIP_NAMED_READ39235028468_V"+str(version)+"_AUTHORIZATION " if successor else "A1_SIP_NAMED_READ39235028468_AUTHORIZATION ",
        window=named_read_window(c,control) if successor else None)
    c.require(comment["id"]==comment_id and c.encoded(terms)==c.encoded(named_read_terms(c,control))
        and c.utc(READ392_WINDOW[1])<=c.utc(comment["created_at"]),"NAMED_READ_GRANT")
    if version==3:
        pr=c.gh_json(f"repos/{c.REPO}/pulls/{control['deployment']['pull_request']}")
        c.require(pr.get("merged") is True and pr.get("merge_commit_sha")==control["expected_master"]
            and pr.get("head",{}).get("sha")==control["deployment"]["reviewed_head"]
            and isinstance(pr.get("merged_at"),str)
            and c.utc(pr["merged_at"])<=c.utc(comment["created_at"]),"NAMED_READ_GRANT_DEPLOYMENT")
    return c.digest(c.encoded(proof)),comment["created_at"]


def named_read_gate_transport(c,job_id):
    """Read genuine log bytes privately; observations never contain raw output.

    File spooling has a process timeout, not a hard download/disk byte cap.
    Only the bounded prefixes are loaded into memory or hashed. The caller
    receives original bytes only after the full file-size and UTF-8 checks.
    """
    c.require(type(job_id) is int and job_id>0,"NAMED_READ_GATE_LOG_JOB")
    record=dict(reason="CLI_HELP",returncode=None,http_status=None,
        stdout_bytes=0,stderr_bytes=0,stdout_prefix_sha256=c.digest(b""),
        stderr_prefix_sha256=c.digest(b""),stdout_utf8=False,
        escape_flag=False,raw_or_headers_emitted=False,
        prefix_read_limits=dict(stdout=2_000_001,stderr=8193),
        hard_capture_byte_limit=None)
    # Version numbers alone cannot establish flag support. Never retry a GET
    # to detect the flag and never enable it for a terminal or caller-owned fd.
    with c.tempfile.TemporaryFile() as help_output:
        try:
            result=c.subprocess.run(["gh","api","--help"],stdout=help_output,
                stderr=c.subprocess.DEVNULL,timeout=10)
            help_output.seek(0);help_raw=help_output.read(65_537)
        except Exception:return b"",record
        if result.returncode!=0 or len(help_raw)>65_536:return b"",record
    flag=b"--allow-escape-sequences" in help_raw
    record["escape_flag"]=flag
    argv=["gh","api"]+(["--allow-escape-sequences"] if flag else [])+[
        f"repos/{c.REPO}/actions/jobs/{job_id}/logs"]
    with c.tempfile.TemporaryFile() as output,c.tempfile.TemporaryFile() as errors:
        failure=None
        try:
            result=c.subprocess.run(argv,stdout=output,stderr=errors,timeout=45)
            record["returncode"]=result.returncode
        except c.subprocess.TimeoutExpired:failure="TIMEOUT"
        except Exception:failure="PROCESS_ERROR"
        output.seek(0,2);record["stdout_bytes"]=output.tell();output.seek(0)
        errors.seek(0,2);record["stderr_bytes"]=errors.tell();errors.seek(0)
        raw,error=output.read(2_000_001),errors.read(8193)
    record["stdout_prefix_sha256"]=c.digest(raw)
    record["stderr_prefix_sha256"]=c.digest(error)
    status=c.re.search(rb"HTTP ([1-5][0-9]{2})",error)
    record["http_status"]=int(status[1]) if status else None
    try:raw.decode("utf-8");record["stdout_utf8"]=True
    except UnicodeError:pass
    reason=(failure or ("STDERR_TOO_LARGE" if record["stderr_bytes"]>=8193 else
        "BODY_TOO_LARGE" if record["stdout_bytes"]>2_000_000 else
        "PROCESS_EXIT" if record["returncode"]!=0 else
        "UTF8" if not record["stdout_utf8"] else "OK"))
    if reason=="PROCESS_EXIT":
        if b"Resource not accessible by integration" in error:reason="INTEGRATION_FORBIDDEN"
        elif b"API rate limit exceeded" in error:reason="RATE_LIMIT"
        elif b"the response contains terminal escape sequences" in error:reason="CLI_ESCAPE_GUARD"
    record["reason"]=reason
    return (raw if reason=="OK" else b""),record


def named_read_gate_log(c,job_id):
    # Keep original ANSI/BOM/UTF-8 bytes: genuine gate parsing stays unchanged.
    raw,record=named_read_gate_transport(c,job_id)
    if record["reason"]!="OK":raise c.Refused("NAMED_READ_GATE_LOG_"+record["reason"]) from None
    return raw.decode("utf-8")


def named_read_gate(c,control,check):
    # These are the existing trusted gate bytes at reviewed base3c6c216, not
    # newly trusted PR/runner pins. A changed protected implementation must stop.
    output=check.get("output",{})
    evidence=("ATTESTED_EXACT_HEAD_REVIEW","MAINTAINER_BOUND_CLEAN_REACTION")
    summaries={"Evidence: "+e+"\n\nFailures: none\n\nUnresolved conversations are enforced separately by master branch protection." for e in evidence}
    c.require(type(check.get("id")) is int and type(check.get("check_suite",{}).get("id")) is int
        and output.get("title")=="PASS_REVIEW_COMPLETE" and output.get("summary") in summaries
        and isinstance(check.get("started_at"),str) and isinstance(check.get("completed_at"),str),
        "NAMED_READ_GATE_PROVENANCE")
    started=c.utc(check["started_at"]);completed=c.utc(check["completed_at"])
    c.require(started<=completed,"NAMED_READ_GATE_PROVENANCE")
    query=c.urlencode(dict(created=(started-c.timedelta(hours=1)).isoformat()+".."+completed.isoformat(),per_page=100))
    runs=c.gh_json(f"repos/{c.REPO}/actions/workflows/317164841/runs?{query}")
    c.require(isinstance(runs.get("workflow_runs"),list)
        and runs.get("total_count")==len(runs["workflow_runs"])<=100,"NAMED_READ_GATE_PROVENANCE")
    candidates=[r for r in runs["workflow_runs"] if r.get("workflow_id")==317164841
        and r.get("path")==".github/workflows/review_complete_gate.yml"
        and r.get("event") in {"issue_comment","workflow_dispatch"}
        and r.get("status")=="completed" and r.get("conclusion")=="success"
        and r.get("repository",{}).get("full_name")==c.REPO and r.get("head_repository",{}).get("full_name")==c.REPO
        and isinstance(r.get("created_at"),str) and isinstance(r.get("updated_at"),str)
        and c.utc(r["created_at"])<=started<=completed<=c.utc(r["updated_at"])]
    c.require(0<len(candidates)<=5,"NAMED_READ_GATE_PROVENANCE")
    proofs=[]
    for run in candidates:
        c.require(type(run.get("id")) is int and type(run.get("run_attempt")) is int
            and run["run_attempt"]>=1 and c.re.fullmatch("[0-9a-f]{40}",run.get("head_sha", "")),
            "NAMED_READ_GATE_PROVENANCE")
        jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{run['id']}/jobs?per_page=100")
        c.require(jobs.get("total_count")==len(jobs.get("jobs",[]))==1,"NAMED_READ_GATE_PROVENANCE")
        job=jobs["jobs"][0]
        c.require(type(job.get("id")) is int and job.get("run_id")==run["id"]
            and job.get("name")=="evaluate" and job.get("status")=="completed" and job.get("conclusion")=="success"
            and isinstance(job.get("started_at"),str) and isinstance(job.get("completed_at"),str)
            and c.utc(job["started_at"])<=started<=completed<=c.utc(job["completed_at"]),"NAMED_READ_GATE_PROVENANCE")
        for name in ("Checkout trusted gate implementation","Resolve trusted head observation and maintainer attestation",
                     "Evaluate Codex review evidence for current head","Publish required review_complete check on PR head"):
            steps=[s for s in job.get("steps",[]) if s.get("name")==name]
            c.require(len(steps)==1 and steps[0].get("status")=="completed"
                and steps[0].get("conclusion")=="success","NAMED_READ_GATE_PROVENANCE")
        text="\n".join(line.partition(" ")[2] for line in named_read_gate_log(c,job["id"]).splitlines())
        records=[]
        for match in c.re.finditer(r"(?m)^\{",text):
            try:records.append(c.json.JSONDecoder().raw_decode(text,match.start())[0])
            except ValueError:continue
        published=[r for r in records if isinstance(r,dict) and r.get("id")==check["id"] and r.get("name")=="review_complete"]
        if not published:continue
        c.require(len(published)==1 and all(published[0].get(k)==check.get(k) for k in
            ("head_sha","status","conclusion","check_suite","output")),"NAMED_READ_GATE_PROVENANCE")
        evaluations=[r for r in records if isinstance(r,dict) and r.get("schema_version")=="run287-review-complete-gate-v2"]
        c.require(len(evaluations)==1,"NAMED_READ_GATE_PROVENANCE")
        result=evaluations[0]
        c.require(result.get("status")=="PASS_REVIEW_COMPLETE" and result.get("passed") is True
            and result.get("head_sha")==control["deployment"]["reviewed_head"]
            and result.get("pull_request_number")==control["deployment"]["pull_request"]
            and result.get("evidence_type") in evidence and result.get("failures")==[],"NAMED_READ_GATE_PROVENANCE")
        checkouts=c.re.findall(r"(?m)^\[command\].*git log -1 --format=%H\n([0-9a-f]{40})$",text)
        c.require(len(checkouts)==1,"NAMED_READ_GATE_PROVENANCE")
        for ref in {run["head_sha"],checkouts[0]}:
            for path,sha in READ392_GATE_PINS.items():
                remote=c.gh_json(f"repos/{c.REPO}/contents/{path}?ref={ref}")
                c.require(remote.get("encoding")=="base64"
                    and c.digest(c.base64.b64decode(remote.get("content","")))==sha,"NAMED_READ_GATE_PROVENANCE")
        proofs.append((run["id"],job["id"]))
    c.require(len(proofs)==1,"NAMED_READ_GATE_PROVENANCE")


def named_read_checks(c,control):
    head=control["deployment"]["reviewed_head"]
    checks=c.gh_json(f"repos/{c.REPO}/commits/{head}/check-runs?per_page=100")
    c.require(checks.get("total_count")==len(checks.get("check_runs",[]))<=100,"NAMED_READ_CHECKS")
    for name in ("validate","offline","review_complete"):
        selected=[x for x in checks["check_runs"] if x.get("name")==name]
        c.require(len(selected)==1 and selected[0].get("head_sha")==head
            and selected[0].get("status")=="completed" and selected[0].get("conclusion")=="success"
            and selected[0].get("app",{}).get("slug")=="github-actions","NAMED_READ_CHECKS")
        if name=="review_complete":named_read_gate(c,control,selected[0])


def named_read_origin(c,control):
    # Preserve the real650 clock while independently reviewing corrective code.
    origin=control["window_origin"]
    c.require(c.encoded(origin)==c.encoded(READ392_V3_ORIGIN),"NAMED_READ_WINDOW_ORIGIN")
    pr=c.gh_json(f"repos/{c.REPO}/pulls/{origin['pull_request']}")
    c.require(pr.get("merged") is True and pr.get("draft") is False
        and pr.get("number")==origin["pull_request"]
        and pr.get("base",{}).get("ref")=="master"
        and pr.get("base",{}).get("repo",{}).get("full_name")==c.REPO
        and pr.get("head",{}).get("repo",{}).get("full_name")==c.REPO
        and pr.get("head",{}).get("sha")==origin["reviewed_head"]
        and pr.get("merge_commit_sha")==origin["source_sha"]
        and pr.get("merged_at")==origin["merged_at_utc"],"NAMED_READ_WINDOW_ORIGIN")
    for ref in (origin["reviewed_head"],origin["source_sha"]):
        commit=c.gh_json(f"repos/{c.REPO}/git/commits/{ref}")
        c.require(commit.get("tree",{}).get("sha")==origin["tree_sha"],"NAMED_READ_WINDOW_ORIGIN")
    named_read_checks(c,dict(deployment=dict(pull_request=origin["pull_request"],reviewed_head=origin["reviewed_head"])))


def named_read_deployed(c,control,*,accounting=False):
    # A new read still needs the live tip. Historical cost import/reflush binds
    # only the actual immutable deployment; unrelated master changes are not it.
    if not accounting:
        branch=c.gh_json(f"repos/{c.REPO}/branches/master")
        c.require(branch.get("protected") is True and branch.get("commit",{}).get("sha")==control["expected_master"],
                  "CAMPAIGN_MASTER_DRIFT")
    pins={}
    for path in V6_PINS:
        remote=c.gh_json(f"repos/{c.REPO}/contents/{path}?ref={control['expected_master']}")
        local=c.digest(c.bounded_bytes(c.ROOT/path,262144).replace(b"\r\n",b"\n"))
        c.require(remote.get("encoding")=="base64"
            and c.digest(c.base64.b64decode(remote.get("content","")))==local,"NAMED_READ_CODE_PINS")
        pins[path]=local
    c.require(set(pins)==set(V6_PINS) and c.digest(c.encoded(pins))==control["code_pins_sha256"],
              "NAMED_READ_CODE_PINS")
    number=control["deployment"]["pull_request"];head=control["deployment"]["reviewed_head"]
    pr=c.gh_json(f"repos/{c.REPO}/pulls/{number}")
    c.require(pr.get("merged") is True and pr.get("draft") is False
        and pr.get("number")==number and pr.get("base",{}).get("ref")=="master"
        and pr.get("base",{}).get("repo",{}).get("full_name")==c.REPO
        and pr.get("head",{}).get("repo",{}).get("full_name")==c.REPO and pr.get("head",{}).get("sha")==head
        and pr.get("merge_commit_sha")==control["expected_master"],"NAMED_READ_PROTECTED_DEPLOYMENT")
    if named_read_version(control)>=2:
        start,end=named_read_window(c,control)
        if named_read_version(control)==3:
            named_read_origin(c,control)
            c.require(isinstance(pr.get("merged_at"),str)
                and c.utc(start)<=c.utc(pr["merged_at"])<c.utc(end)
                and c.utc(pr["merged_at"])<=c.utc(),"NAMED_READ_DEPLOYMENT_WINDOW")
        else:
            c.require(pr.get("merged_at")==start and c.utc(start)<=c.utc(),
                      "NAMED_READ_DEPLOYMENT_WINDOW")
    # Squash may change the commit ID; the complete reviewed tree must survive.
    reviewed=c.gh_json(f"repos/{c.REPO}/git/commits/{head}")
    deployed=c.gh_json(f"repos/{c.REPO}/git/commits/{control['expected_master']}")
    c.require(isinstance(reviewed.get("tree",{}).get("sha"),str)
        and c.re.fullmatch("[0-9a-f]{40}",reviewed["tree"]["sha"])
        and reviewed["tree"]["sha"]==deployed.get("tree",{}).get("sha"),"NAMED_READ_DEPLOYED_TREE")
    named_read_checks(c,control)
    # Hosting/review-complete protection is not replaced by a client assertion:
    # require the real merged protected PR and its genuine repository signal.
    if not accounting:
        branch=c.gh_json(f"repos/{c.REPO}/branches/master")
        c.require(branch.get("protected") is True and branch.get("commit",{}).get("sha")==control["expected_master"],
                  "CAMPAIGN_MASTER_DRIFT")
    return pins


def named_read_prefix(c,runs,control,current):
    c.require(isinstance(runs,list) and len(runs)==30 and runs[-1]==current
        and [r.get("id") for r in runs[:-1]]==BASIS_IDS+[REFUSAL_RUN,CONTROL_RUN,
            39225295971,39227056047,39228995303,39230864255,39232902584,39235028468]
        and type(current.get("id")) is int and current["id"]>39235028468
        and type(current.get("run_attempt")) is int and current["run_attempt"]==1
        and current.get("head_sha")==control["expected_master"] and current.get("head_branch")=="master"
        and current.get("event")=="workflow_dispatch"
        and current.get("display_title")=="a1-sip "+control["nonce"]+" native-read39235028468"
        and current.get("status") in {"in_progress","completed"},"NAMED_READ_SINGLE_USE")
    c.require(all(control["nonce"] not in x.get("display_title","") for x in runs[:-1]),
              "NAMED_READ_NONCE_REUSE")
    return runs[:-1]


def named_read_budget(c,observed):
    c.require(len(observed["runs"])==29 and observed["runs"][-1]["id"]==39235028468
        and observed["examined"]==296 and observed["parent_sha"]==READ392_CP
        and c.digest(c.encoded(observed["receipts"][-1]))==READ392_METER
        and observed["used"]==READ392_USED and observed["active_seconds"]==8736
        and observed["first"]==c.utc(c.CONTINUATION["first"]),"NAMED_READ_CAPTURE_PREFIX")
    c.require(all(READ392_USED[k]+READ392_ALLOWANCE[k]<=c.CONTINUED_LIMITS[k] for k in c.LIMITS)
        and 8736+900<=43200 and 29+1<=40,"NAMED_READ_SHARED_BUDGET")


def named_read_queries(folder):
    return {
        "name = '"+READ392_CP+".json' and '"+folder+"' in parents and trashed = false":"2",
        "'"+folder+"' in parents and trashed = false and createdTime >= '"+READ392_WINDOW[0]
        +"' and createdTime <= '"+READ392_WINDOW[1]+"'":"8"}


def named_read_job_deadline(c,jobs,*,control=None):
    c.require(jobs.get("total_count")==len(jobs.get("jobs",[]))==2,"NAMED_READ_JOB")
    offline=[j for j in jobs["jobs"] if j.get("name")=="offline" and j.get("status")=="completed"
             and j.get("conclusion")=="success"]
    active=[j for j in jobs["jobs"] if j.get("name")=="reconcile" and j.get("status")=="in_progress"]
    c.require(len(offline)==len(active)==1 and isinstance(offline[0].get("completed_at"),str)
        and isinstance(active[0].get("started_at"),str)
        and c.utc(offline[0]["completed_at"])<=c.utc(active[0]["started_at"])<=c.utc()+c.timedelta(seconds=5),
        "NAMED_READ_JOB_CLOCK")
    end=named_read_window(c,control)[1] if control is not None else VALIDITY_END
    # Preserve sixty seconds of the existing five-minute job for final save
    # and the always-run meter upload. This does not enlarge any time budget.
    return min(c.utc(active[0]["started_at"])+c.timedelta(seconds=240),c.utc(end))


def named_read_meter(c,*args,control,refresh_needed=False,**kwargs):
    kwargs.setdefault("clock",c.utc)
    class NamedReadMeter(c.RuntimeMeter):
        def __init__(self):
            self.result={};self.attempts=[];self.pending=None;self.seen=set()
            self.response_settlement=None
            auth=control["authorization"]
            self.root=auth["private_root_folder_id"];self.folder=auth["private_data_folder_id"]
            self.cp_id=control["checkpoint_file_id"];self.candidate_id=None
            self.media_sizes={self.cp_id:5005};self.queries=named_read_queries(self.folder)
            self.refresh_needed=refresh_needed
            self.initial_save=True
            super().__init__(*args,**kwargs)
            self.initial_save=False

        def save(self):
            # A signal or failed durability barrier may interrupt the caller.
            # Publish one coherent settlement before serializing any state.
            if self.response_settlement is not None:
                self.used,self.observed_google_body_bytes,self.attempts=self.response_settlement
                self.response_settlement=None
            # RuntimeMeter publishes its complete debit dictionary at once.
            # If its save fails, keep the matching conservative attempt too.
            if self.pending is not None and len(self.attempts)+1==self.used["drive_requests"]:
                self.attempts=self.attempts+[dict(self.pending)]
            try:self.write_snapshot()
            except Exception:
                if self.initial_save and self.pending is None and not self.attempts \
                        and all(v==0 for v in self.used.values()):
                    # Constructor has not returned: its caller cannot finalize
                    # this object. Retry once as zero-I/O BLOCKED, never capture.
                    self.initial_save=False
                    try:self.finish("BLOCKED","NAMED_READ_METER_INIT")
                    finally:raise c.Refused("NAMED_READ_METER_INIT") from None
                raise

        def write_snapshot(self):
            c.atomic_json(self.journal,dict(schema="a1-named-read39235028468-meter-v"+str(named_read_version(control)),**self.identity,
                usage=self.used,allowance=self.allowance,status=self.status,reason=self.reason,
                finalized=self.finalized,transfer_definition=c.METRIC,attempts=self.attempts,
                observed_google_body_bytes=self.observed_google_body_bytes,result=self.result,
                capture_allowed=False,source_admission=False,pit_verified=False,economic_authority=False,
                **({"last_transport_failure":self.last_transport_failure} if self.last_transport_failure else {})),
                unique_temporary=True)
            c.sync_native18_settlement(self.journal)

        def reserve_storage(self,size):
            raise c.Refused("NAMED_READ_WRITE_BLOCKED")

        def debit(self,changes):
            c.require(self.pending is not None and changes==dict(drive_requests=1,drive_bytes=self.pending["reservation"]),
                      "NAMED_READ_DEBIT")
            super().debit(changes)

        def settle_google_response(self,body,raw,limit):
            usage=dict(self.used);usage["drive_bytes"]-=limit+1-len(raw)
            attempts=[dict(a) for a in self.attempts[:-1]]+[dict(self.attempts[-1],status="COMPLETE",response_bytes=len(raw))]
            observed=self.observed_google_body_bytes+len(body or b"")+len(raw)
            self.response_settlement=(usage,observed,attempts)
            self.save()

        def perform(self,url,*,method="GET",body=None,**kw):
            from urllib.parse import parse_qsl,urlsplit
            c.require(self.pending is None,"NAMED_READ_PENDING")
            p=urlsplit(url);pairs=parse_qsl(p.query,keep_blank_values=True);q=dict(pairs)
            allowed=False;kind=None;limit=2_000_000;key=(p.netloc,p.path,tuple(sorted(q.items())),method)
            c.require(not p.fragment and len(pairs)==len(q),"NAMED_READ_ENDPOINT")
            if url=="https://oauth2.googleapis.com/token" and method=="POST" and self.refresh_needed:
                allowed=True;kind="OAUTH";limit=65536
                c.require(isinstance(body,bytes) and 0<len(body)<=65536,"NAMED_READ_OAUTH_BODY")
            elif p.scheme=="https" and p.netloc=="www.googleapis.com" and method=="GET" and body is None:
                if p.path=="/drive/v3/about":
                    allowed=q=={"fields":"user(permissionId),storageQuota"};kind="ABOUT"
                elif p.path=="/drive/v3/files":
                    allowed=set(q)=={"q","pageSize","fields"} and self.queries.get(q.get("q"))==q.get("pageSize") \
                        and q.get("fields")==READ392_FIELDS
                    kind="POSITIVE_LIST" if q.get("pageSize")=="2" else "WINDOW_LIST"
                elif p.path.startswith("/drive/v3/files/"):
                    file_id=p.path.removeprefix("/drive/v3/files/")
                    if q=={"alt":"media"}:
                        allowed=file_id in self.media_sizes;kind="CP_MEDIA" if file_id==self.cp_id else "CANDIDATE_MEDIA"
                        if allowed:limit=self.media_sizes[file_id]
                    else:
                        expected=READ392_CHECK_FIELDS if file_id in {self.root,self.folder} else READ392_META_FIELDS
                        allowed=file_id in {self.root,self.folder,self.cp_id,self.candidate_id} and q=={"fields":expected}
                        kind="METADATA"
            c.require(allowed and key not in self.seen,"NAMED_READ_ENDPOINT")
            supplied=kw.get("limit",limit)
            c.require(type(supplied) is int and supplied>0,"NAMED_READ_RESPONSE_BOUND")
            kw["limit"]=min(supplied,limit)
            self.seen.add(key)
            attempt=dict(ordinal=len(self.attempts)+1,kind=kind,limit=kw["limit"],
                request_body_bytes=len(body or b""),reservation=kw["limit"]+1+len(body or b"")+65536,
                status="RESERVED",response_bytes=None)
            self.pending=attempt
            try:
                raw=super().perform(url,method=method,body=body,**kw)
            except BaseException:
                # The underlying meter retains a full reservation on transport
                # failure. Keep pending for a final save even if interrupted
                # between publishing the debit and entering its save method.
                raise
            else:
                self.pending=None
                return raw

    return NamedReadMeter()


def named_read_item(c,item,folder):
    c.require(isinstance(item,dict) and set(item)=={"id","name","size","parents","createdTime"}
        and isinstance(item["id"],str) and c.re.fullmatch(r"[A-Za-z0-9_-]{10,100}",item["id"])
        and isinstance(item["name"],str) and c.re.fullmatch(r"[0-9a-f]{64}\.(?:zip|jsonl\.gz|json)",item["name"])
        and isinstance(item["size"],str) and c.re.fullmatch(r"[1-9][0-9]{0,7}",item["size"])
        and int(item["size"])<=16_000_000 and item["parents"]==[folder]
        and isinstance(item["createdTime"],str) and c.utc(item["createdTime"])<=c.utc(),
        "NAMED_READ_ITEM")
    return item


def named_read_metadata(c,drive,file_id,folder):
    info=drive.get("files/"+file_id,{"fields":READ392_META_FIELDS})
    c.require(isinstance(info,dict) and info.get("id")==file_id and info.get("trashed") is False
        and info.get("shared") is False and info.get("mimeType")!="application/vnd.google-apps.folder"
        and info.get("permissions")==[dict(id=drive.owner,type="user",role="owner")],
        "NAMED_READ_PRIVATE_OBJECT")
    item={k:info.get(k) for k in ("id","name","size","parents","createdTime")}
    return named_read_item(c,item,folder)


def named_read_content(c,raw,item,auth):
    # Inspect content identity only. No reconstruction, recovery or PIT inference.
    from tools import alpaca_sip_private_backfill_v1 as cap
    import io,zipfile,gzip
    names=cap.external_cohort(auth["external_cohort"]["input_csv"].encode())[296:300]
    role="UNKNOWN";identity_verified=False
    try:
        if item["name"].endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                entries=z.infolist()
                c.require(0<len(entries)<=2*cap.MAX_PAGES+1 and len({i.filename for i in entries})==len(entries)
                    and all(c.re.fullmatch(r"[0-9a-f]{64}\.json|capture\.json",i.filename) for i in entries)
                    and sum(i.file_size for i in entries)<=128_000_000,"NAMED_READ_CONTENT")
                manifest=next((i for i in entries if i.filename=="capture.json"),None)
                c.require(manifest is not None and manifest.file_size<=65536,"NAMED_READ_CONTENT")
                value=c.decode(z.read(manifest))
            identity_verified=isinstance(value,dict) and value.get("source")==cap.SOURCE \
                and value.get("source_sha")==auth["expected_master"] and value.get("symbols")==names \
                and value.get("cohort_scope")==auth["external_cohort"]["scope"] \
                and value.get("start")=="2016-01-04" and value.get("end")=="2026-10-14"
            role="RAW_ARCHIVE"
        elif item["name"].endswith(".jsonl.gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
                decoded=f.read(16_000_001)
            c.require(len(decoded)<=16_000_000,"NAMED_READ_CONTENT")
            rows=[c.decode(line) for line in decoded.splitlines()]
            identity_verified=bool(rows) and all(isinstance(x,dict) and x.get("ticker") in names
                and x.get("adjustment") in {"raw","split"} for x in rows)
            role="NORMALIZED"
        else:
            value=c.decode(raw);role="JSON"
            identity_verified=isinstance(value,dict) and value.get("cohort_scope")==auth["external_cohort"]["scope"] \
                and value.get("source_sha")==auth["expected_master"] and value.get("symbols")==names
    except c.Refused:raise
    except Exception:raise c.Refused("NAMED_READ_CONTENT") from None
    return dict(role=role,content_identity_verified=identity_verified,failed_post_equivalence_verified=False)


def named_read_objects(c,drive,control,meter):
    from tools import alpaca_sip_private_backfill_v1 as cap
    auth=control["authorization"];folder=auth["private_data_folder_id"]
    c.require(c.digest(drive.owner.encode())==c.CONTINUATION["bindings"]["owner_sha256"],"NAMED_READ_OWNER")
    drive.check(folder,auth["private_root_folder_id"])
    cp_meta=named_read_metadata(c,drive,control["checkpoint_file_id"],folder)
    c.require(cp_meta["name"]==READ392_CP+".json" and cp_meta["size"]=="5005","NAMED_READ_CP_METADATA")
    raw=drive.read(control["checkpoint_file_id"],5005)
    c.require(len(raw)==5005 and c.digest(raw)==READ392_CP,"NAMED_READ_CP_HASH")
    cp=c.decode(raw)
    c.require(isinstance(cp,dict) and cp.get("examined")==cap.external_cohort(
        auth["external_cohort"]["input_csv"].encode())[:296]
        and cp.get("cohort_scope")==auth["external_cohort"]["scope"],"NAMED_READ_CP_CONTENT")
    def listed(query):
        result=c.credential_safe_json(drive.request("https://www.googleapis.com/drive/v3/files?"+
            c.urlencode(dict(q=query,pageSize=meter.queries[query],fields=READ392_FIELDS))),(drive.token,))
        c.require(isinstance(result,dict) and set(result)=={"files"} and isinstance(result["files"],list),
                  "NAMED_READ_LIST_INCOMPLETE")
        return result["files"]
    positive,window=meter.queries
    items=listed(positive)
    c.require(items==[cp_meta],"NAMED_READ_POSITIVE_CONTROL")
    items=listed(window)
    c.require(len(items)<=8,"NAMED_READ_LIST_INCOMPLETE")
    seen=set();candidates=[]
    for item in items:
        named_read_item(c,item,folder)
        c.require(item["id"] not in seen and c.utc(READ392_WINDOW[0])<=c.utc(item["createdTime"])<=c.utc(READ392_WINDOW[1]),
                  "NAMED_READ_INVENTORY_IDENTITY")
        seen.add(item["id"])
        if item["size"]=="434796":candidates.append(item)
    c.require(len(candidates)<=1,"NAMED_READ_DUPLICATE_CANDIDATE")
    # If the positive object is in the inclusive window it must also be listed.
    if c.utc(READ392_WINDOW[0])<=c.utc(cp_meta["createdTime"])<=c.utc(READ392_WINDOW[1]):
        c.require(cp_meta in items,"NAMED_READ_LIST_INCOMPLETE")
    result=dict(positive_control_verified=True,positive_server_created_at=cp_meta["createdTime"],
        files_count=len(items),inventory_sha256=c.digest(c.encoded(items)),candidate_count=len(candidates),
        owner_sha256=c.digest(drive.owner.encode()),absence_proven=False,failed_request_body_hash_known=False,
        failed_post_equivalence_verified=False,origin_status="UNKNOWN")
    # Private diagnostic bytes are never included in the public meter artifact.
    c.atomic_json(meter.journal.parent/"named_read_objects.private.json",dict(positive=cp_meta,files=items))
    if candidates:
        item=candidates[0];meter.candidate_id=item["id"];meter.media_sizes[item["id"]]=434796
        actual=named_read_metadata(c,drive,item["id"],folder)
        c.require(actual==item,"NAMED_READ_CANDIDATE_METADATA")
        body=drive.read(item["id"],434796)
        c.require(len(body)==434796 and c.digest(body)==item["name"][:64],"NAMED_READ_CANDIDATE_HASH")
        result.update(candidate_sha256=c.digest(body),candidate_bytes=len(body),
            candidate_server_created_at=item["createdTime"],**named_read_content(c,body,item,auth))
    meter.result=result;meter.save()
    return result


def named_read_event_control(c,expected=None):
    # Do not put private control/IDs in Actions step env: it is logged before
    # a later add-mask command can protect it. Read the genuine runner event.
    event=c.bounded_json(c.os.environ.get("GITHUB_EVENT_PATH",""),65536)
    inputs=event.get("inputs") if isinstance(event,dict) else None
    c.require(isinstance(inputs,dict) and isinstance(inputs.get("campaign_control"),str)
        and 0<len(inputs["campaign_control"].encode())<=16384,"NAMED_READ_EVENT")
    value=c.decode(inputs["campaign_control"])
    auth=named_read_control(c,value)
    c.require((expected is None or c.encoded(value)==c.encoded(expected))
        and inputs.get("campaign_nonce")==value["nonce"]
        and inputs.get("private_root_folder_id")==auth["private_root_folder_id"]
        and inputs.get("private_data_folder_id")==auth["private_data_folder_id"]
        and all(inputs.get(k) is True or inputs.get(k)=="true" for k in
            ("private_research_authorized","noncommercial_terms_acknowledged")),"NAMED_READ_EVENT_BINDING")
    c.require(not any(c.os.getenv(k) for k in ("INPUT_CAMPAIGN_CONTROL","INPUT_PRIVATE_ROOT_FOLDER_ID",
        "INPUT_PRIVATE_DATA_FOLDER_ID","INPUT_RESUME_FILE_ID")),"NAMED_READ_PRIVATE_ENV")
    return value


def named_read_worker(c,control,state_dir):
    from tools.twelve_private_capture import OwnerDrive
    auth=named_read_control(c,control)
    named_read_event_control(c,control)
    c.require(c.os.getenv("GITHUB_REPOSITORY")==c.REPO and c.os.getenv("GITHUB_REF")=="refs/heads/master"
        and c.os.getenv("GITHUB_SHA")==control["expected_master"] and c.os.getenv("GITHUB_RUN_ATTEMPT")=="1"
        and c.os.getenv("INPUT_NATIVE_READ_ONLY")=="true"
        and c.os.getenv("A1_PRIVATE_RESEARCH_AUTHORIZED")=="true"
        and c.os.getenv("ALPACA_NONCOMMERCIAL_ACKNOWLEDGED")=="true"
        and c.os.getenv("INPUT_CAMPAIGN_NONCE")==control["nonce"],"NAMED_READ_CONTEXT")
    proof,created=named_read_proof(c,control)
    source_pins=named_read_deployed(c,control)
    current=c.gh_json(f"repos/{c.REPO}/actions/runs/{int(c.os.environ['GITHUB_RUN_ID'])}")
    start,end=named_read_window(c,control)
    c.require(current.get("status")=="in_progress" and isinstance(current.get("created_at"),str)
        and c.utc(start)<=c.utc(created)<=c.utc(current["created_at"])<c.utc(end),"NAMED_READ_RUN_CLOCK")
    # Historical capture clocks stay unchanged. Only this reviewed diagnostic
    # uses its independently proved deployment window, never a price worker.
    observed=c.external_history(auth,allow_stopped=True,
        enforce_expiry=named_read_version(control)<2,named_read_context=(control,current))
    named_read_budget(c,observed)
    jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{current['id']}/jobs?per_page=100")
    deadline=named_read_job_deadline(c,jobs,control=control)
    directory=c.Path(state_dir);directory.mkdir(exist_ok=False)
    identity=dict(task_key=READ392_TASK,run_id=current["id"],run_attempt=1,nonce=control["nonce"],
        control_sha256=c.digest(c.encoded(control)),grant_proof_sha256=proof,
        source_sha=control["expected_master"],source_pins=source_pins,
        parent_checkpoint_sha256=READ392_CP,examined_before=296,failed_run_id=39235028468,
        failed_meter_sha256=READ392_METER,usage_before=dict(READ392_USED),
        active_seconds_before=8736,dispatches_before=29,active_seconds_reservation=900,dispatch_reservation=1)
    # History reconstruction and job lookups may outlive a concurrent merge.
    # Recheck the protected tip after those reads, immediately before secrets.
    branch=c.gh_json(f"repos/{c.REPO}/branches/master")
    c.require(branch.get("protected") is True and branch.get("commit",{}).get("sha")==control["expected_master"],
              "CAMPAIGN_MASTER_DRIFT")
    # Only inspect whether the existing OwnerDrive bootstrap needs a refresh;
    # no credential value is emitted, copied to metadata or sent to GitHub.
    config=c.configparser.ConfigParser(interpolation=None)
    try:
        config.read_string(c.os.environ.get("MACRO_DRIVE_CONFIG",""))
        token=c.decode(config["gdrive"]["token"])
        expiry=token.get("expiry",token.get("Expiry"))
        c.require(isinstance(expiry,str),"DRIVE_CONFIGURATION")
        # OwnerDrive rechecks expiry before every request. Cover the complete
        # transport window, retaining the existing one-refresh endpoint key.
        refresh_needed=c.utc(expiry)<=deadline+c.timedelta(seconds=60)
    except Exception:raise c.Refused("DRIVE_CONFIGURATION") from None
    meter=named_read_meter(c,READ392_ALLOWANCE,directory/"native_read_meter.json",deadline.isoformat(),
        identity,limits=c.CONTINUED_LIMITS,control=control,refresh_needed=refresh_needed)
    try:
        with meter.process_deadline(),c.tempfile.TemporaryDirectory(prefix="a1-named-read-") as temp:
            drive=OwnerDrive(auth["private_root_folder_id"],temp,meter=meter)
            named_read_objects(c,drive,control,meter)
        meter.finish("COMPLETE")
    except c.Refused as exc:
        meter.finish("BLOCKED",str(exc));raise
    except Exception:
        meter.finish("BLOCKED","NAMED_READ_INTERNAL")
        raise c.Refused("NAMED_READ_INTERNAL") from None
    return dict(status="NAMED_READ_COMPLETE",capture_allowed=False,source_admission=False)


def named_read_cost(c,control,run,value,jobs):
    version=named_read_version(control);successor=version>=2
    schema="a1-named-read39235028468-meter-v"+str(version)
    c.require(isinstance(value,dict) and value.get("schema")==schema
        and value.get("task_key")==READ392_TASK
        and value.get("control_sha256")==c.digest(c.encoded(control))
        and value.get("run_id")==run["id"] and type(value.get("run_id")) is int
        and type(value.get("run_attempt")) is int and value["run_attempt"]==1
        and value.get("nonce")==control["nonce"] and value.get("source_sha")==control["expected_master"]
        and isinstance(value.get("source_pins"),dict) and set(value["source_pins"])==set(V6_PINS)
        and c.digest(c.encoded(value["source_pins"]))==control["code_pins_sha256"]
        and value.get("parent_checkpoint_sha256")==READ392_CP and value.get("examined_before")==296
        and value.get("failed_run_id")==39235028468 and value.get("failed_meter_sha256")==READ392_METER
        and value.get("usage_before")==READ392_USED and value.get("active_seconds_before")==8736
        and value.get("dispatches_before")==29 and value.get("active_seconds_reservation")==900
        and value.get("dispatch_reservation")==1 and value.get("finalized") is True
        and value.get("status") in {"COMPLETE","BLOCKED"} and value.get("transfer_definition")==c.METRIC
        and c.encoded(value.get("allowance"))==c.encoded(READ392_ALLOWANCE)
        and all(value.get(k) is False for k in ("capture_allowed","source_admission","pit_verified","economic_authority")),
        "NAMED_READ_COST_RECEIPT")
    usage=value.get("usage");attempts=value.get("attempts")
    c.require(isinstance(usage,dict) and set(usage)==set(c.LIMITS)
        and all(type(usage[k]) is int and 0<=usage[k]<=READ392_ALLOWANCE[k] for k in c.LIMITS)
        and isinstance(attempts,list) and len(attempts)==usage["drive_requests"],"NAMED_READ_COST_COUNTER")
    charged=0;observed=0;pending=False
    for i,a in enumerate(attempts,1):
        c.require(isinstance(a,dict) and set(a)=={"ordinal","kind","limit","request_body_bytes","reservation","status","response_bytes"}
            and type(a["ordinal"]) is int and a["ordinal"]==i
            and a["kind"] in {"OAUTH","ABOUT","POSITIVE_LIST","WINDOW_LIST","METADATA","CP_MEDIA","CANDIDATE_MEDIA"}
            and type(a["limit"]) is int and 0<a["limit"]<=
                (65536 if a["kind"]=="OAUTH" else 5005 if a["kind"]=="CP_MEDIA" else 434796
                 if a["kind"]=="CANDIDATE_MEDIA" else 2_000_000)
            and type(a["request_body_bytes"]) is int and 0<=a["request_body_bytes"]<=65536
            and (a["kind"]=="OAUTH" or a["request_body_bytes"]==0)
            and type(a["reservation"]) is int
            and a["reservation"]==a["limit"]+1+a["request_body_bytes"]+65536,"NAMED_READ_COST_ATTEMPT")
        if a["status"]=="COMPLETE":
            c.require(not pending and type(a["response_bytes"]) is int
                and 0<a["response_bytes"]<=a["limit"],"NAMED_READ_COST_ATTEMPT")
            observed+=a["request_body_bytes"]+a["response_bytes"]
            charged+=a["request_body_bytes"]+a["response_bytes"]+65536
        else:
            c.require(a["status"]=="RESERVED" and a["response_bytes"] is None and i==len(attempts)
                and value["status"]=="BLOCKED","NAMED_READ_COST_ATTEMPT")
            pending=True;charged+=a["reservation"]
    c.require(charged==usage["drive_bytes"] and observed==value.get("observed_google_body_bytes"),
              "NAMED_READ_COST_CONSERVATION")
    c.require(run.get("status")=="completed" and run.get("run_attempt")==1
        and run.get("head_sha")==control["expected_master"] and run.get("head_branch")=="master"
        and run.get("event")=="workflow_dispatch"
        and run.get("display_title")=="a1-sip "+control["nonce"]+" native-read39235028468"
        and isinstance(run.get("created_at"),str)
        and run.get("conclusion") in {"success","failure","cancelled","timed_out"}
        and (value["status"]=="COMPLETE" or run.get("conclusion")!="success"),
        "NAMED_READ_COST_RUN")
    c.require(jobs.get("total_count")==len(jobs.get("jobs",[]))==2
        and {j.get("name") for j in jobs["jobs"]}=={"offline","reconcile"},"NAMED_READ_COST_JOBS")
    seconds=0
    for j in jobs["jobs"]:
        c.require(j.get("status")=="completed" and isinstance(j.get("started_at"),str)
            and isinstance(j.get("completed_at"),str) and c.utc(run["created_at"])<=c.utc(j["started_at"])
            <=c.utc(j["completed_at"]),"NAMED_READ_COST_CLOCK")
        seconds+=c.math.ceil((c.utc(j["completed_at"])-c.utc(j["started_at"])).total_seconds())
    c.require(0<seconds<=900,"NAMED_READ_COST_CLOCK")
    if value["status"]=="COMPLETE" and run["conclusion"]!="success":
        reconcile=next(j for j in jobs["jobs"] if j["name"]=="reconcile")
        steps=reconcile.get("steps",[])
        read=[s for s in steps if s.get("name")=="Reconcile exact failed Drive POST with native metered reads"]
        upload=[s for s in steps if s.get("name")=="Preserve native read meter without original bytes or private IDs"]
        c.require(len(read)==len(upload)==1 and read[0].get("status")=="completed"
            and read[0].get("conclusion")=="success" and isinstance(read[0].get("started_at"),str)
            and isinstance(read[0].get("completed_at"),str) and isinstance(upload[0].get("started_at"),str)
            and c.utc(reconcile["started_at"])<=c.utc(read[0]["started_at"])<=c.utc(read[0]["completed_at"])
            <=c.utc(upload[0]["started_at"])<=c.utc(reconcile["completed_at"]),"NAMED_READ_COST_STEP_PROOF")
    result=value.get("result")
    c.require(isinstance(result,dict) and (not result or all(result.get(k) is False for k in
        ("absence_proven","failed_request_body_hash_known","failed_post_equivalence_verified"))),
        "NAMED_READ_COST_ORIGIN")
    if value["status"]=="COMPLETE":
        c.require(result.get("positive_control_verified") is True and result.get("origin_status")=="UNKNOWN"
            and type(result.get("candidate_count")) is int and 0<=result["candidate_count"]<=1,
            "NAMED_READ_COST_ORIGIN")
    if successor:
        start,end=named_read_window(c,control)
        # Cleanup may finish after expiry. Retain those actual failed costs;
        # the transport deadline already forbids new reads beyond the window.
        c.require(c.utc(start)<=c.utc(run["created_at"])<c.utc(end),"NAMED_READ_COST_CLOCK")
    return dict(schema="a1-named-read39235028468-cost-settlement-v"+str(version),run_id=run["id"],run_attempt=1,
        source_sha=control["expected_master"],control_sha256=c.digest(c.encoded(control)),
        meter_sha256=c.digest(c.encoded(value)),grant_proof_sha256=value.get("grant_proof_sha256"),
        checkpoint_sha256=READ392_CP,failed_meter_sha256=READ392_METER,
        usage=dict(usage),usage_after={k:READ392_USED[k]+usage[k] for k in c.LIMITS},
        active_seconds=seconds,active_seconds_after=8736+seconds,dispatches=1,dispatches_after=30,
        unknown_storage_bytes_still_charged=[302101,434796],absence_proven=False,
        failed_request_body_hash_known=False,failed_post_equivalence_verified=False,
        source_admission=False,pit_verified=False,economic_authority=False,total_platform_cost_verified=False)


def named_read_append_cost(c,registry,payload):
    # Called only under the existing family writer lock after canonical proof.
    entries=registry.entries
    c.require(registry.lock_owned and len(entries) in {75,76},"NAMED_READ_SETTLEMENT_PREFIX")
    tail=registry.directory/"000075.json"
    c.require(c.digest(c.bounded_bytes(tail))==READ392_FAMILY
        and entries[74].get("kind")=="SETTLED" and entries[74].get("run_id")==39235028468,
        "NAMED_READ_SETTLEMENT_PREFIX")
    if len(entries)==75:
        c.require(registry.parent==READ392_FAMILY,"NAMED_READ_SETTLEMENT_PREFIX")
        registry.append("NAMED_READ39235028468_SETTLED",**payload)
    entry=registry.entries[-1]
    c.require(entry.get("kind")=="NAMED_READ39235028468_SETTLED" and entry.get("previous_sha256")==READ392_FAMILY
        and {k:entry.get(k) for k in payload}==payload
        and set(entry)==set(payload)|{"sequence","kind","auth_sha256","previous_sha256","recorded_utc"},
        "NAMED_READ_SETTLEMENT_CONFLICT")
    path=registry.directory/"000076.json"
    c.require(c.bounded_bytes(path)==c.encoded(entry),"NAMED_READ_SETTLEMENT_BYTES")
    # Reflush both barriers even when recovering a visible interrupted append.
    c.sync_native18_settlement(path)
    return entry


def named_read_frozen_prefix(c,directory,count,tail):
    c.require(directory.is_dir() and not directory.is_symlink()
        and sorted(p.name for p in directory.glob("*.json"))==[f"{i:06d}.json" for i in range(1,count+1)],
        "NAMED_READ_JOURNAL_PREFIX")
    previous=None
    for i in range(1,count+1):
        path=directory/f"{i:06d}.json"
        raw=c.bounded_bytes(path);entry=c.decode(raw)
        c.require(not path.is_symlink() and isinstance(entry,dict) and type(entry.get("sequence")) is int
            and entry["sequence"]==i and entry.get("previous_sha256")==previous,"NAMED_READ_JOURNAL_PREFIX")
        previous=c.digest(raw)
    c.require(previous==tail,"NAMED_READ_JOURNAL_PREFIX")


def named_read_settle_host(c,args):
    control=c.bounded_json(args.native392_settle_control,16384)
    auth=named_read_control(c,control,accounting=True)
    proof,_=named_read_proof(c,control,accounting=True)
    named_read_deployed(c,control,accounting=True)
    run=c.gh_json(f"repos/{c.REPO}/actions/runs/{args.native392_run_id}")
    observed=c.external_history(auth,allow_stopped=True,enforce_expiry=False,named_read_context=(control,run))
    named_read_budget(c,observed)
    artifacts=c.gh_json(f"repos/{c.REPO}/actions/runs/{run['id']}/artifacts?per_page=100")
    c.require(artifacts.get("total_count")==len(artifacts.get("artifacts",[]))<=100,"NAMED_READ_ARTIFACT")
    selected=[a for a in artifacts["artifacts"] if a.get("name")=="a1-native-drive-read-meter"]
    c.require(len(selected)==1 and selected[0].get("expired") is False
        and type(selected[0].get("id")) is int and type(selected[0].get("size_in_bytes")) is int
        and 0<selected[0]["size_in_bytes"]<=65536,"NAMED_READ_ARTIFACT")
    with c.tempfile.TemporaryDirectory(prefix="a1-named-cost-") as temp:
        result=c.subprocess.run(["gh","run","download",str(run["id"]),"--repo",c.REPO,
            "--name","a1-native-drive-read-meter","--dir",temp],
            stdout=c.subprocess.DEVNULL,stderr=c.subprocess.DEVNULL,timeout=45)
        files=list(c.Path(temp).iterdir())
        c.require(result.returncode==0 and len(files)==1 and files[0].name=="native_read_meter.json"
            and not files[0].is_symlink(),"NAMED_READ_ARTIFACT")
        value=c.bounded_json(files[0])
    c.require(value.get("grant_proof_sha256")==proof,"NAMED_READ_COST_GRANT")
    jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{run['id']}/jobs?per_page=100")
    payload=named_read_cost(c,control,run,value,jobs)
    payload["artifact_id"]=selected[0]["id"]
    # Do not synthesize a missing original/capture/cohort journal or settlement.
    budget=c.Path(args.budget_state_dir).resolve();state=c.Path(args.state_dir).resolve()
    c.require(state==budget.parent/"external-cohort-top500-20261017","NAMED_READ_JOURNAL_PREFIX")
    named_read_frozen_prefix(c,budget,17,c.CONTINUATION["event"])
    named_read_frozen_prefix(c,state,48,READ392_COHORT)
    registry=c.external_family_registry(budget,auth,state)
    try:
        # All remote reads before this final complete canonical-history check.
        final_proof,_=named_read_proof(c,control,accounting=True)
        named_read_deployed(c,control,accounting=True)
        fresh=c.external_history(auth,allow_stopped=True,enforce_expiry=False,named_read_context=(control,run))
        named_read_budget(c,fresh)
        c.require(final_proof==proof,"NAMED_READ_COST_GRANT")
        return named_read_append_cost(c,registry,payload)
    finally:registry.close()



# The one actual pre-meter failure is an accounting proof, never a RuntimeMeter
# or an extra read/capture slot. These immutable historical bytes stay distinct
# from the currently reviewed implementation that verifies and imports them.
READ30_RUN=39544804083
READ30_SOURCE="3d6de8f354015bb93a73b87eac4f3648c6ea453a"
READ30_HEAD="691d8fe5d0695c09270b9a1782f42ac96e55cbb7"
READ30_TREE="5577fe263abd4da12d6eb4e7058ddf605300cc88"
READ30_CONTROL="40cb2c3c0644d6d72cb457ad761e468f8bd373e814eabdadf977d93efb42e0c1"
READ30_LOG="3e2fa8ae6903b694f1e6c4d584034d4e88e3a3cf4ebf266216494b93fb79287d"
READ30_JOBS="82e67c9a86be68b5aa30f4785adf48e0b5dc8a043fb64def993850f2f86153a6"
READ30_JOB_SECURITY="7566456d503ac4e2909e2d0979dc1d8eeda7b6e0b54b89bdba924dd70a063cf7"
READ30_ARTIFACTS="bf6638afd0bdbf03a3236bb78ff0fe1a70b76eb9f5ba9b8102624fde8ac48cef"
READ30_PINS={
    ".github/workflows/alpaca_sip_private_backfill_v1.yml":"0a84712dc6c9303d852658413fb7c1adb3861279cb371c1a4154a049ee456664",
    "tools/alpaca_sip_campaign.py":"5ed5b68b43df5f79a0f5fe1faf3d7cfff92475c2371a1946f588a1bad20bb8ec",
    "tools/alpaca_sip_source_revision.py":"39af64ce013a4c61befc071f3708cc0da1530f184d6be1b6c2e7ab5178102478",
    "tools/alpaca_sip_private_backfill_v1.py":"01e94b59f4a587cf54b5bf5b6b25740c7eae8da12358817323d890a379180ec1",
    "tools/configure_macro_research_drive.py":"51c6210ae63f4e7522d5d73d8eb90c5c03348736a9638461772d116fcf51d2fc",
    "tools/macro_history_sources.py":"029ae7337618211c1520adc78c9199831ed739918070c6b29204e9110aa9ab08",
    "tools/twelve_private_capture.py":"2cfe64847cb6a9d4777247968832dbdf5737eafc1ed5f47a2e7b6877bc27bdac"}
READ30_KIND="NAMED_READ39544804083_PREMETER_CLOSED"


def named_read30_control(c,control):
    auth=named_read_control(c,control,accounting=True)
    c.require(named_read_version(control)==3 and c.digest(c.encoded(control))==READ30_CONTROL
        and control["expected_master"]==READ30_SOURCE
        and control["deployment"]==dict(pull_request=657,reviewed_head=READ30_HEAD)
        and control["code_pins_sha256"]==c.digest(c.encoded(READ30_PINS))
        and control["grant_reference"]=="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6308087601",
        "NAMED_READ30_CONTROL")
    return auth


def named_read30_deployment(c,control):
    # No comparison of old remote bytes with today's local implementation.
    named_read_origin(c,control)
    pr=c.gh_json(f"repos/{c.REPO}/pulls/657")
    c.require(pr.get("number")==657 and pr.get("merged") is True and pr.get("draft") is False
        and pr.get("merge_commit_sha")==READ30_SOURCE and pr.get("merged_at")=="2026-10-21T04:26:23Z"
        and pr.get("head",{}).get("sha")==READ30_HEAD
        and pr.get("base",{}).get("ref")=="master"
        and pr.get("base",{}).get("repo",{}).get("full_name")==c.REPO
        and pr.get("head",{}).get("repo",{}).get("full_name")==c.REPO,"NAMED_READ30_DEPLOYMENT")
    for ref in (READ30_HEAD,READ30_SOURCE):
        commit=c.gh_json(f"repos/{c.REPO}/git/commits/{ref}")
        c.require(commit.get("tree",{}).get("sha")==READ30_TREE,"NAMED_READ30_DEPLOYMENT")
    blobs={}
    for path,sha in READ30_PINS.items():
        value=c.gh_json(f"repos/{c.REPO}/contents/{path}?ref={READ30_SOURCE}")
        c.require(value.get("encoding")=="base64","NAMED_READ30_SOURCE")
        try:raw=c.base64.b64decode(value.get("content",""),validate=False)
        except Exception:raise c.Refused("NAMED_READ30_SOURCE") from None
        c.require(c.digest(raw)==sha,"NAMED_READ30_SOURCE");blobs[path]=raw
    named_read_checks(c,control)
    return blobs


def named_read30_job_security(jobs):
    keys=("id","run_id","name","status","conclusion","started_at","completed_at","head_sha","head_branch")
    fields=("name","status","conclusion","number","started_at","completed_at")
    return dict(total_count=jobs.get("total_count"),jobs=[dict(**{k:j.get(k) for k in keys},
        steps=[{k:s.get(k) for k in fields} for s in j.get("steps",[])]) for j in jobs.get("jobs",[])])


def named_read30_failure(c,control,run,jobs,artifacts,blobs,raw,proof,grant_created_at):
    named_read30_control(c,control)
    c.require(isinstance(proof,str) and c.re.fullmatch("[0-9a-f]{64}",proof)
        and set(blobs)==set(READ30_PINS) and all(c.digest(blobs[k])==h for k,h in READ30_PINS.items()),
        "NAMED_READ30_SOURCE")
    c.require(type(run.get("id")) is int and run["id"]==READ30_RUN
        and type(run.get("run_attempt")) is int and run["run_attempt"]==1
        and run.get("head_sha")==READ30_SOURCE and run.get("head_branch")=="master"
        and run.get("workflow_id")==382519204 and run.get("path")==".github/workflows/alpaca_sip_private_backfill_v1.yml"
        and run.get("repository",{}).get("full_name")==c.REPO
        and run.get("head_repository",{}).get("full_name")==c.REPO
        and run.get("event")=="workflow_dispatch" and run.get("status")=="completed"
        and run.get("conclusion")=="failure"
        and run.get("display_title")=="a1-sip "+control["nonce"]+" native-read39235028468"
        and isinstance(run.get("created_at"),str)
        and c.utc("2026-10-21T04:26:23Z")<=c.utc(run["created_at"])<=c.utc("2026-10-21T04:34:47Z"),
        "NAMED_READ30_RUN")
    start_window,end_window=named_read_window(c,control)
    c.require(isinstance(grant_created_at,str) and c.utc(start_window)<=c.utc(grant_created_at)
        <=c.utc(run["created_at"])<c.utc(end_window),"NAMED_READ30_GRANT_CLOCK")
    # Retained full-file hashes remain audit references. Fresh API comparison
    # authenticates security fields without depending on avatars or new URLs.
    c.require(c.digest(c.encoded(named_read30_job_security(jobs)))==READ30_JOB_SECURITY and jobs.get("total_count")==2
        and len(jobs.get("jobs",[]))==2,"NAMED_READ30_JOBS")
    expected=[(119040439144,"offline","success","2026-10-21T04:34:47Z","2026-10-21T04:37:02Z"),
              (119041111801,"reconcile","failure","2026-10-21T04:37:05Z","2026-10-21T04:38:25Z")]
    c.require([(j.get("id"),j.get("name"),j.get("conclusion"),j.get("started_at"),j.get("completed_at"))
        for j in jobs["jobs"]]==expected and all(j.get("status")=="completed"
            and j.get("run_id")==READ30_RUN and j.get("head_sha")==READ30_SOURCE
            and j.get("head_branch")=="master" for j in jobs["jobs"]),
        "NAMED_READ30_JOBS")
    # Artifact absence corroborates the failure; it is never the zero-I/O proof.
    c.require(artifacts.get("total_count")==0 and artifacts.get("artifacts")==[],"NAMED_READ30_ARTIFACTS")
    c.require(isinstance(raw,bytes) and len(raw)<=2_000_000 and c.digest(raw)==READ30_LOG,"NAMED_READ30_LOG")
    try:text=raw.decode("utf-8-sig")
    except UnicodeError:raise c.Refused("NAMED_READ30_LOG") from None
    witness='{"status": "BLOCKED", "code": "NAMED_READ_GATE_LOG", "source_admission": false}'
    rows=[line for line in text.splitlines() if witness in line]
    c.require(len(rows)==1 and text.count(witness)==1,"NAMED_READ30_WITNESS")
    match=c.re.fullmatch(r"([^ ]+) "+c.re.escape(witness),rows[0])
    c.require(match is not None,"NAMED_READ30_WITNESS")
    steps=jobs["jobs"][1].get("steps",[])
    step=[s for s in steps if s.get("name")=="Reconcile exact failed Drive POST with native metered reads"]
    capture=[s for s in steps if s.get("name")=="Collect immutable owner-only Alpaca history"]
    c.require(len(step)==1 and step[0].get("status")=="completed" and step[0].get("conclusion")=="failure"
        and isinstance(step[0].get("started_at"),str) and isinstance(step[0].get("completed_at"),str)
        and len(capture)==1 and capture[0].get("conclusion")=="skipped",
        "NAMED_READ30_STEP")
    # API step clocks have whole-second precision; the log has fractional seconds.
    when=c.utc(match[1]);start=c.utc(step[0]["started_at"]);end=c.utc(step[0]["completed_at"])
    c.require(c.utc(expected[1][3])<=start<=when<end+c.timedelta(seconds=1)
        and end<=c.utc(expected[1][4]),"NAMED_READ30_CLOCK")
    # Frozen source hashes authenticate the positive error and its call order.
    # The failed deployed guard precedes configuration parsing, meter and Drive.
    import ast
    tree=ast.parse(blobs["tools/alpaca_sip_source_revision.py"].decode("utf-8"))
    worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="named_read_worker")
    calls=[(n.lineno,n.func.id) for n in ast.walk(worker) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    guard=[line for line,name in calls if name=="named_read_deployed"]
    meter=[line for line,name in calls if name=="named_read_meter"]
    owner=[line for line,name in calls if name=="OwnerDrive"]
    config=[n.lineno for n in ast.walk(worker) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Attribute) and n.func.attr=="ConfigParser"]
    c.require(len(guard)==len(meter)==len(owner)==len(config)==1
        and guard[0]<config[0]<meter[0]<owner[0],"NAMED_READ30_BOUNDARY")
    seconds=sum(c.math.ceil((c.utc(j["completed_at"])-c.utc(j["started_at"])).total_seconds()) for j in jobs["jobs"])
    c.require(seconds==215,"NAMED_READ30_CLOCK")
    return dict(schema="a1-named-read39544804083-premeter-cost-closure-v1",
        run_id=READ30_RUN,run_attempt=1,source_sha=READ30_SOURCE,reviewed_head=READ30_HEAD,tree_sha=READ30_TREE,
        source_pins_sha256=c.digest(c.encoded(READ30_PINS)),control_sha256=READ30_CONTROL,
        grant_proof_sha256=proof,checkpoint_sha256=READ392_CP,failed_meter_sha256=READ392_METER,
        failure_log_sha256=READ30_LOG,retained_terminal_jobs_sha256=READ30_JOBS,
        terminal_jobs_security_sha256=READ30_JOB_SECURITY,retained_artifact_metadata_sha256=READ30_ARTIFACTS,
        original_meter_sha256=None,not_runtime_meter=True,status="PREMETER_REFUSED",reason="NAMED_READ_GATE_LOG",
        usage={k:0 for k in c.LIMITS},usage_after=dict(READ392_USED),active_seconds=215,active_seconds_after=8951,
        dispatches=1,dispatches_after=30,unknown_storage_bytes_still_charged=[302101,434796],
        zero_io_basis="EXACT_DEPLOYED_SOURCE_ORDER_AND_POSITIVE_FAILURE_LOG",absence_is_zero_io_basis=False,
        original_transport_detail="UNOBSERVED",read_verification_complete=False,absence_proven=False,
        failed_request_body_hash_known=False,failed_post_equivalence_verified=False,capture_authorized=False,
        new_diagnostic_authorized=False,budget_reset=False,source_admission=False,pit_verified=False,
        economic_authority=False,total_platform_cost_verified=False)


def named_read30_append(c,registry,payload):
    c.require(registry.lock_owned and len(registry.entries) in {75,76},"NAMED_READ30_PREFIX")
    c.require(c.digest(c.bounded_bytes(registry.directory/"000075.json"))==READ392_FAMILY
        and registry.entries[74].get("kind")=="SETTLED"
        and registry.entries[74].get("run_id")==39235028468,"NAMED_READ30_PREFIX")
    if len(registry.entries)==75:
        c.require(registry.parent==READ392_FAMILY,"NAMED_READ30_PREFIX")
        registry.append(READ30_KIND,**payload)
    entry=registry.entries[-1]
    c.require(entry.get("kind")==READ30_KIND and entry.get("previous_sha256")==READ392_FAMILY
        and {k:entry.get(k) for k in payload}==payload
        and set(entry)==set(payload)|{"sequence","kind","auth_sha256","previous_sha256","recorded_utc"},
        "NAMED_READ30_CONFLICT")
    path=registry.directory/"000076.json"
    c.require(c.bounded_bytes(path)==c.encoded(entry),"NAMED_READ30_BYTES")
    c.sync_native18_settlement(path)
    return entry


def named_read30_host(c,args):
    # Explicit host-only accounting; no credentials, Drive, meter or dispatch.
    c.require(args.native392_premeter_publication and args.budget_state_dir
        and not any(getattr(args,k) is not None for k in (
            "authorization","native_read_control","native18_settle_authorization","native392_settle_control",
            "native392_run_id","native18_deployed_master","refusal_close_authorization",
            "control_refusal_close_authorization","control_refusal_log","control_refusal_jobs","recovery_run",
            "account_permission_reference","predispatch_recovery","continuation_receipt","cohort_input","max_batches")),
        "NAMED_READ30_MODE")
    control=c.bounded_json(args.native392_premeter_control,16384)
    auth=named_read30_control(c,control)
    publication=c.bounded_json(args.native392_premeter_publication,1024)
    c.require(isinstance(publication,dict) and set(publication)=={"expected_master","deployment","code_pins_sha256"}
        and isinstance(publication["expected_master"],str) and c.re.fullmatch("[0-9a-f]{40}",publication["expected_master"])
        and isinstance(publication["deployment"],dict) and set(publication["deployment"])=={"pull_request","reviewed_head"}
        and type(publication["deployment"]["pull_request"]) is int and publication["deployment"]["pull_request"]>660
        and isinstance(publication["deployment"]["reviewed_head"],str)
        and c.re.fullmatch("[0-9a-f]{40}",publication["deployment"]["reviewed_head"])
        and isinstance(publication["code_pins_sha256"],str)
        and c.re.fullmatch("[0-9a-f]{64}",publication["code_pins_sha256"]),"NAMED_READ30_PUBLICATION")
    named_read_deployed(c,publication)
    proof,created=named_read_proof(c,control,accounting=True)
    blobs=named_read30_deployment(c,control)
    run=c.gh_json(f"repos/{c.REPO}/actions/runs/{READ30_RUN}")
    observed=c.external_history(auth,allow_stopped=True,enforce_expiry=False,named_read_context=(control,run))
    named_read_budget(c,observed)
    jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{READ30_RUN}/jobs?per_page=100")
    artifacts=c.gh_json(f"repos/{c.REPO}/actions/runs/{READ30_RUN}/artifacts?per_page=100")
    raw=named_read_gate_log(c,119041111801).encode("utf-8")
    payload=named_read30_failure(c,control,run,jobs,artifacts,blobs,raw,proof,created)
    budget=c.Path(args.budget_state_dir).resolve();state=c.Path(args.state_dir).resolve()
    c.require(state==budget.parent/"external-cohort-top500-20261017","NAMED_READ30_PREFIX")
    named_read_frozen_prefix(c,budget,17,c.CONTINUATION["event"])
    named_read_frozen_prefix(c,state,48,READ392_COHORT)
    registry=c.external_family_registry(budget,auth,state)
    try:
        final_proof,_=named_read_proof(c,control,accounting=True)
        fresh=c.external_history(auth,allow_stopped=True,enforce_expiry=False,named_read_context=(control,run))
        named_read_budget(c,fresh)
        c.require(final_proof==proof,"NAMED_READ30_CONTROL")
        named_read_deployed(c,publication)  # Live tip check is last, under the writer lock.
        entry=named_read30_append(c,registry,payload)
        return dict(status="EXACT_READ30_PREMETER_COST_CLOSED",receipt_sha256=c.digest(c.encoded(entry)),
            run_id=READ30_RUN,active_seconds=215,active_seconds_after=8951,dispatches_after=30,
            not_runtime_meter=True,read_verification_complete=False,new_price_subjects=0,capture_authorized=False)
    finally:registry.close()


# Separate frozen174 cohort. No expansion of the old993/417 seed or its caps.
PRICE174_SCHEMA="a1-sp500-gap174-capture-v1"
PRICE174_TASK="R1000-A1-SP500-PRIORITY-CAPTURE-20261020"
PRICE174_INPUT="b36152639bf4c64780c74beba1aeb48aacac4e7d9fba8ecdae77ed4b3c6a9329"
PRICE174_INVENTORY="d97c707586147d191debb1883526f594065c6b523956f311fba52376205c395a"
PRICE174_SCOPE=dict(task_key=PRICE174_TASK,namespace="sp500-gap-20261020",input_sha256=PRICE174_INPUT)


def price174_old(c,value):
    import zlib
    c.require(isinstance(value,str) and len(value)<=12000,"PRICE174_PACK")
    try:
        packed=c.base64.b64decode(value,validate=True)
        decoder=zlib.decompressobj();raw=decoder.decompress(packed,16385)
        c.require(len(raw)<=16384 and decoder.eof and not decoder.unconsumed_tail
            and not decoder.unused_data and c.digest(raw)==READ30_CONTROL,"PRICE174_PACK")
        old=c.decode(raw)
        c.require(c.encoded(old)==raw,"PRICE174_PACK")
        named_read30_control(c,old)
        return old
    except c.Refused:raise
    except Exception:raise c.Refused("PRICE174_PACK") from None


def price174_hash(c,auth):
    return c.digest(c.encoded({k:v for k,v in auth.items() if k!="grant_reference"}))


def price174_auth(c,auth):
    from tools import alpaca_sip_private_backfill_v1 as cap
    c.require(isinstance(auth,dict) and set(auth)=={"schema","task_key","scope","input_csv",
        "frozen_inventory_sha256","prior_control_zlib","expected_master","code_pins_sha256","deployment",
        "execution_window","human_window_authority_sha256","closure_event","grant_reference"}
        and len(c.encoded(auth))<=15000 and auth["schema"]==PRICE174_SCHEMA and auth["task_key"]==PRICE174_TASK
        and auth["scope"]==PRICE174_SCOPE and auth["frozen_inventory_sha256"]==PRICE174_INVENTORY
        and isinstance(auth["input_csv"],str) and c.digest(auth["input_csv"].encode())==PRICE174_INPUT,
        "PRICE174_AUTH")
    names=cap.external_cohort(auth["input_csv"].encode())
    c.require(len(names)==len(set(names))==174,"PRICE174_INPUT")
    old=price174_old(c,auth["prior_control_zlib"]);prior=old["authorization"]
    before=cap.external_cohort(prior["external_cohort"]["input_csv"].encode())
    c.require(before[296:300]==["MSCI","BSBR","STM","FMX"] and not set(names)&set(before[:300]),
        "PRICE174_DISJOINT")
    for key,size in (("expected_master",40),("code_pins_sha256",64),("human_window_authority_sha256",64)):
        c.require(isinstance(auth[key],str) and c.re.fullmatch("[0-9a-f]{"+str(size)+"}",auth[key])
            and auth[key]!="0"*size,"PRICE174_AUTH")
    c.require(auth["human_window_authority_sha256"] not in {READ392_V2_AUTHORITY,VALIDITY_AUTHORITY},
        "PRICE174_NEW_WINDOW_AUTHORITY")
    deployment=auth["deployment"];window=auth["execution_window"]
    c.require(isinstance(deployment,dict) and set(deployment)=={"pull_request","reviewed_head"}
        and type(deployment["pull_request"]) is int and deployment["pull_request"]>660
        and isinstance(deployment["reviewed_head"],str) and c.re.fullmatch("[0-9a-f]{40}",deployment["reviewed_head"])
        and isinstance(window,dict) and set(window)=={"deployed_at_utc","expires_at_utc"}
        and all(isinstance(window[k],str) for k in window)
        and c.utc(window["expires_at_utc"])-c.utc(window["deployed_at_utc"])==c.timedelta(seconds=86400)
        and c.utc(window["deployed_at_utc"])>c.utc(READ392_V3_ORIGIN["merged_at_utc"]),
        "PRICE174_WINDOW")
    entry=auth["closure_event"]
    c.require(isinstance(entry,dict) and entry.get("kind")==READ30_KIND and entry.get("sequence")==76
        and entry.get("previous_sha256")==READ392_FAMILY
        and entry.get("auth_sha256")==c.external_family_genesis() and isinstance(entry.get("recorded_utc"),str)
        and c.utc("2026-10-21T04:38:25Z")<=c.utc(entry["recorded_utc"])<=c.utc(),
        "PRICE174_CLOSURE")
    c.require(isinstance(auth["grant_reference"],str) and c.re.fullmatch(
        r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",auth["grant_reference"]),
        "PRICE174_GRANT")
    return old,names


def price174_terms(c,auth):
    old,names=price174_auth(c,auth);prior=old["authorization"]
    return dict(schema="a1-sp500174-price-execution-grant-v1",task_key=PRICE174_TASK,
        authorization_sha256=price174_hash(c,auth),source_sha=auth["expected_master"],deployment=auth["deployment"],
        code_pins_sha256=auth["code_pins_sha256"],scope=PRICE174_SCOPE,input_sha256=PRICE174_INPUT,input_count=174,
        frozen_inventory_sha256=PRICE174_INVENTORY,prior_control_sha256=READ30_CONTROL,
        closure_event_sha256=c.digest(c.encoded(auth["closure_event"])),
        human_window_authority_sha256=auth["human_window_authority_sha256"],execution_window=auth["execution_window"],
        private_bindings_sha256=c.digest(c.encoded({k:prior[k] for k in
            ("private_root_folder_id","private_data_folder_id","credential_binding","owner_permission_id")})),
        start="2016-01-04",end_exclusive="2026-10-14",timeframe="1Day",feed="sip",adjustments=["raw","split"],
        batches=[32,32,32,32,32,14],usage_before=dict(READ392_USED),active_seconds_before=8951,dispatches_before=30,
        limits=dict(c.CONTINUED_LIMITS),active_seconds_limit=43200,dispatch_limit=40,
        unknown_storage_still_charged=[302101,434796],old_uncertain_group_quarantined=["MSCI","BSBR","STM","FMX"],
        old417_resume_authorized=False,unknown_post_retry_authorized=False,refund_authorized=False,
        account_migration_authorized=False,capture_authorized=True,private_noncommercial_research_only=True,
        source_admission=False,pit_verified=False,economic_authority=False,budget_reset=False,
        total_platform_cost_verified=False)


def price174_authority(c,auth,*,accounting=False):
    old,names=price174_auth(c,auth)
    publication={k:auth[k] for k in ("expected_master","deployment","code_pins_sha256")}
    named_read_deployed(c,publication,accounting=accounting)
    pr=c.gh_json(f"repos/{c.REPO}/pulls/{auth['deployment']['pull_request']}")
    window=auth["execution_window"];start,end=window["deployed_at_utc"],window["expires_at_utc"]
    c.require(pr.get("merged_at")==start,"PRICE174_WINDOW_ORIGIN")
    ref=int(auth["grant_reference"].rsplit("-",1)[1])
    comment=c.gh_json(f"repos/{c.REPO}/issues/comments/{ref}")
    terms,proof=human_record(c,comment,"A1_SP500174_PRICE_EXECUTION_AUTHORIZATION ",window=(start,end))
    c.require(comment["id"]==ref and c.encoded(terms)==c.encoded(price174_terms(c,auth))
        and c.utc(auth["closure_event"]["recorded_utc"])<=c.utc(comment["created_at"]),"PRICE174_GRANT")
    if not accounting:c.require(c.utc(start)<=c.utc()<c.utc(end),"CAMPAIGN_EXPIRED")
    return dict(proof_sha256=c.digest(c.encoded(proof)),proof_updated_utc=comment["created_at"],expires_at_utc=end)


def price174_prefix(c,runs,auth,old):
    price174_auth(c,auth)
    c.require(isinstance(runs,list) and 30<=len(runs)<=36 and runs[29].get("id")==READ30_RUN,
        "PRICE174_HISTORY")
    prefix=named_read_prefix(c,runs[:30],old,runs[29])
    for run in runs[30:]:
        c.require(type(run.get("id")) is int and run["id"]>READ30_RUN
            and type(run.get("run_attempt")) is int and run["run_attempt"]==1
            and run.get("head_sha")==auth["expected_master"] and run.get("head_branch")=="master"
            and run.get("event")=="workflow_dispatch" and isinstance(run.get("created_at"),str)
            and c.re.fullmatch("a1-sip "+c.PREFIX+r"[0-9a-f]{24}",run.get("display_title","")),
            "PRICE174_HISTORY")
    return prefix


def price174_closure(c,auth):
    old,_=price174_auth(c,auth)
    proof,created=named_read_proof(c,old,accounting=True)
    blobs=named_read30_deployment(c,old)
    run=c.gh_json(f"repos/{c.REPO}/actions/runs/{READ30_RUN}")
    jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{READ30_RUN}/jobs?per_page=100")
    artifacts=c.gh_json(f"repos/{c.REPO}/actions/runs/{READ30_RUN}/artifacts?per_page=100")
    raw=named_read_gate_log(c,119041111801).encode()
    payload=named_read30_failure(c,old,run,jobs,artifacts,blobs,raw,proof,created)
    entry=auth["closure_event"]
    c.require(set(entry)==set(payload)|{"sequence","kind","auth_sha256","previous_sha256","recorded_utc"}
        and {k:entry.get(k) for k in payload}==payload,"PRICE174_CLOSURE")
    return payload


def price174_seconds(c,run):
    jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{run['id']}/jobs?per_page=100")
    c.require(jobs.get("total_count")==len(jobs.get("jobs",[]))==2
        and {j.get("name") for j in jobs["jobs"]}=={"offline","capture"},"PRICE174_JOB")
    seconds=0
    for job in jobs["jobs"]:
        c.require(job.get("status")=="completed" and isinstance(job.get("started_at"),str)
            and isinstance(job.get("completed_at"),str) and c.utc(run["created_at"])<=c.utc(job["started_at"])
            <=c.utc(job["completed_at"])<=c.utc()+c.timedelta(seconds=1),"PRICE174_JOB_CLOCK")
        seconds+=c.math.ceil((c.utc(job["completed_at"])-c.utc(job["started_at"])).total_seconds())
    c.require(0<seconds<=7800,"PRICE174_JOB_CLOCK")
    return seconds


def price174_history(c,auth,*,current=None,nonce=None):
    old,names=price174_auth(c,auth)
    proof=price174_authority(c,auth,accounting=True)
    price174_closure(c,auth)
    observed=c.external_history(old["authorization"],allow_stopped=True,enforce_expiry=False,
        price174_context=(auth,old))
    named_read_budget(c,observed)
    # The authenticated original source cannot start another group until all
    # four-name checkpoint/readback work has closed. Retain its unknown POST;
    # no symbol in its possible prefix300 footprint belongs to this cohort.
    last=observed["receipts"][-1]
    c.require(last.get("status")=="BLOCKED" and last.get("examined_after")==296
        and last.get("checkpoint_sha256")==READ392_CP,"PRICE174_OLD_FAILURE")
    runs=observed["all_runs"];rows=runs[30:]
    c.require(current is None or rows and rows[-1].get("id")==current
        and rows[-1].get("display_title")=="a1-sip "+nonce,"PRICE174_CURRENT")
    used=dict(READ392_USED);active=8951;n=0;parent=c.external_genesis(PRICE174_SCOPE)
    values=[];durations=[];steps=[]
    window=auth["execution_window"];start,end=map(c.utc,(window["deployed_at_utc"],window["expires_at_utc"]))
    for run in rows:
        c.require(start<=c.utc(run["created_at"])<end,"PRICE174_RUN_WINDOW")
        if current==run["id"]:
            c.require(run.get("status")=="in_progress" and run is rows[-1],"PRICE174_CURRENT")
            continue
        c.require(run.get("status")=="completed","CAMPAIGN_RUN_UNRESOLVED")
        value=c.receipt_for_run(run,price174_hash(c,auth),auth["expected_master"],c.CONTINUED_LIMITS)
        allowance={k:c.CONTINUED_LIMITS[k]-used[k] for k in c.LIMITS}
        count=min(32,174-n)
        c.require(n<174 and value.get("preflight_only") is False and value.get("recovery_run") is None
            and value.get("cohort_scope")==PRICE174_SCOPE and value.get("bindings")==c.CONTINUATION["bindings"]
            and value.get("external_proof_sha256")==proof["proof_sha256"]
            and value.get("parent_checkpoint_sha256")==parent and value.get("examined_before")==n
            and value["allowance"]==allowance and n<=value["examined_after"]<=n+count
            and (value["status"]!="COMPLETE" or value["examined_after"]==n+count),
            "PRICE174_RECEIPT")
        c.require(not values or values[-1]["status"]=="COMPLETE"
            and steps[-1]["run"].get("conclusion")=="success","PRICE174_PRIOR_BLOCKED")
        seconds=price174_seconds(c,run);prior_active=active
        for k in c.LIMITS:used[k]+=value["usage"][k]
        active+=seconds
        c.require(all(used[k]<=c.CONTINUED_LIMITS[k] for k in c.LIMITS) and active<=43200,"CAMPAIGN_BUDGET")
        steps.append(dict(run=run,value=value,remaining=allowance,active_remaining=43200-prior_active,parent_sha=parent))
        n=value["examined_after"];parent=value["checkpoint_sha256"]
        c.require(isinstance(parent,str) and c.re.fullmatch("[0-9a-f]{64}",parent),"PRICE174_CHECKPOINT")
        values.append(value);durations.append(seconds)
    c.require(current is None or n<174 and (not values or values[-1]["status"]=="COMPLETE"
        and steps[-1]["run"].get("conclusion")=="success"),"PRICE174_PRIOR_BLOCKED")
    return dict(all_runs=runs,price_runs=rows,receipts=values,durations=durations,steps=steps,used=used,
        active_seconds=active,examined=n,parent_sha=parent,remaining={k:c.CONTINUED_LIMITS[k]-used[k] for k in c.LIMITS},
        proof=proof,old=old,terminal_blocked=bool(steps and (steps[-1]["run"].get("conclusion")!="success"
            or values[-1]["status"]=="BLOCKED")),new_states={k:sum(v["new_states"][k] for v in values) for k in
            ("VALID_COLLECTED","VERIFIED_NO_DATA","QUARANTINED")})


def price174_event_control(c,expected=None):
    event=c.bounded_json(c.os.environ.get("GITHUB_EVENT_PATH",""),65536)
    inputs=event.get("inputs") if isinstance(event,dict) else None
    c.require(isinstance(inputs,dict) and isinstance(inputs.get("campaign_control"),str)
        and 0<len(inputs["campaign_control"].encode())<=16384,"PRICE174_EVENT")
    control=c.decode(inputs["campaign_control"]);auth=control.get("authorization") if isinstance(control,dict) else None
    old,names=price174_auth(c,auth);prior=old["authorization"]
    c.require(set(control)=={"schema","authorization","nonce","parent_sha256"} and control["schema"]==PRICE174_SCHEMA
        and isinstance(control["nonce"],str) and c.re.fullmatch(c.PREFIX+r"[0-9a-f]{24}",control["nonce"])
        and isinstance(control["parent_sha256"],str) and c.re.fullmatch("[0-9a-f]{64}",control["parent_sha256"])
        and inputs.get("campaign_nonce")==control["nonce"] and inputs.get("private_root_folder_id")==prior["private_root_folder_id"]
        and inputs.get("private_data_folder_id")==prior["private_data_folder_id"] and inputs.get("resume_file_id","")==""
        and inputs.get("resume_sha256")==control["parent_sha256"]
        and all(inputs.get(k) is True or inputs.get(k)=="true" for k in
            ("private_research_authorized","noncommercial_terms_acknowledged"))
        and (expected is None or c.encoded(expected)==c.encoded(control)),"PRICE174_EVENT")
    c.require(not any(c.os.getenv(k) for k in ("INPUT_CAMPAIGN_CONTROL","INPUT_PRIVATE_ROOT_FOLDER_ID",
        "INPUT_PRIVATE_DATA_FOLDER_ID","INPUT_RESUME_FILE_ID")),"PRICE174_PRIVATE_ENV")
    return control


def price174_checkpoint(c,drive,folder,sha):
    query="name = '"+sha+".json' and '"+folder+"' in parents and trashed = false"
    value=c.credential_safe_json(drive.request("https://www.googleapis.com/drive/v3/files?"+c.urlencode(dict(
        q=query,pageSize=2,fields="nextPageToken,files(id,name,size,parents)"))),(drive.token,))
    c.require(isinstance(value,dict) and value.get("nextPageToken") is None
        and isinstance(value.get("files"),list) and len(value["files"])==1,"PRICE174_PRIVATE_CHECKPOINT")
    item=value["files"][0]
    c.require(isinstance(item,dict) and item.get("name")==sha+".json" and item.get("parents")==[folder]
        and isinstance(item.get("id"),str) and c.re.fullmatch("[A-Za-z0-9_-]{10,100}",item["id"])
        and isinstance(item.get("size"),str) and item["size"].isascii() and item["size"].isdigit()
        and len(item["size"])<=8 and 0<int(item["size"])<=16000000,"PRICE174_PRIVATE_CHECKPOINT")
    return dict(file_id=item["id"],sha256=sha,bytes=int(item["size"]))


def price174_worker(c,args,control,journal):
    from contextlib import redirect_stdout,redirect_stderr
    from tools import alpaca_sip_private_backfill_v1 as cap
    from tools.twelve_private_capture import OwnerDrive
    price174_event_control(c,control)
    auth=control["authorization"];old,names=price174_auth(c,auth);prior=old["authorization"]
    c.require(c.os.getenv("GITHUB_REPOSITORY")==c.REPO and c.os.getenv("GITHUB_REF")=="refs/heads/master"
        and c.os.getenv("GITHUB_SHA")==auth["expected_master"] and c.os.getenv("GITHUB_RUN_ATTEMPT")=="1"
        and c.os.getenv("INPUT_NATIVE_READ_ONLY")=="false","PRICE174_CONTEXT")
    run_id=int(c.os.environ["GITHUB_RUN_ID"])
    observed=price174_history(c,auth,current=run_id,nonce=control["nonce"])
    n=observed["examined"];batch=min(32,174-n)
    c.require(n<174 and args.start=="2016-01-04" and args.end=="2026-10-14" and args.max_new_symbols==batch
        and control["parent_sha256"]==observed["parent_sha"] and observed["active_seconds"]+7800<=43200,
        "PRICE174_PARENT")
    proof=price174_authority(c,auth)
    c.require(proof==observed["proof"],"PRICE174_GRANT_DRIFT")
    jobs=c.gh_json(f"repos/{c.REPO}/actions/runs/{run_id}/jobs?per_page=100")
    c.require(jobs.get("total_count")==len(jobs.get("jobs",[]))==2,"PRICE174_JOB")
    capture=[j for j in jobs["jobs"] if j.get("name")=="capture" and j.get("status")=="in_progress"]
    offline=[j for j in jobs["jobs"] if j.get("name")=="offline" and j.get("conclusion")=="success"]
    c.require(len(capture)==len(offline)==1 and isinstance(capture[0].get("started_at"),str)
        and isinstance(offline[0].get("completed_at"),str)
        and c.utc(offline[0]["completed_at"])<=c.utc(capture[0]["started_at"])<=c.utc()+c.timedelta(seconds=5),
        "PRICE174_JOB_CLOCK")
    deadline=min(c.utc(capture[0]["started_at"])+c.timedelta(seconds=7100),c.utc(proof["expires_at_utc"]))
    # All metadata/proof reads precede the last protected-tip check and credentials.
    c.require(c.campaign_runs(prior["workflow_run_floor"])==observed["all_runs"],"PRICE174_CANONICAL_DRIFT")
    branch=c.gh_json(f"repos/{c.REPO}/branches/master")
    c.require(branch.get("protected") is True and branch.get("commit",{}).get("sha")==auth["expected_master"],
        "CAMPAIGN_MASTER_DRIFT")
    key,secret=c.os.getenv("ALPACA_API_KEY","").strip(),c.os.getenv("ALPACA_API_SECRET","").strip()
    c.require(key and secret and c.digest((key+"\0"+secret).encode())==prior["credential_binding"],
        "CAMPAIGN_CREDENTIAL_BINDING")
    identity=dict(task_key=c.TASK,auth_sha256=price174_hash(c,auth),source_sha=auth["expected_master"],
        nonce=control["nonce"],run_id=run_id,run_attempt=1,recovery_run=None,preflight_only=False,
        cohort_scope=PRICE174_SCOPE,external_proof_sha256=proof["proof_sha256"],bindings=c.CONTINUATION["bindings"],
        parent_checkpoint_sha256=observed["parent_sha"],examined_before=n,
        account_permission_reference_sha256=c.digest(prior["external_cohort"]["proof_reference"].encode()),
        account_permission_record_sha256=observed["proof"]["proof_sha256"],
        inherited_read30_closure_sha256=c.digest(c.encoded(auth["closure_event"])),
        price_window_expires_at_utc=proof["expires_at_utc"],total_platform_cost_verified=False)
    c.require(not c.Path(journal).exists(),"PRICE174_METER_REUSE")
    meter=c.RuntimeMeter(observed["remaining"],journal,deadline.isoformat(),identity,
        limits=c.CONTINUED_LIMITS,asset_symbols=names[n:n+batch])
    private_args=c.argparse.Namespace(**vars(args))
    private_args.private_root_folder_id=prior["private_root_folder_id"]
    private_args.private_data_folder_id=prior["private_data_folder_id"]
    private_args.resume_file_id=private_args.resume_sha256=""
    def factory(root,temp):
        drive=OwnerDrive(root,temp,meter=meter)
        c.require((prior["owner_permission_id"] is None or drive.owner==prior["owner_permission_id"])
            and c.digest(drive.owner.encode())==c.CONTINUATION["bindings"]["owner_sha256"]
            and drive.free>=2*1024**3,"CAMPAIGN_OWNER_OR_SPACE")
        meter.identity["free_bytes_at_start"]=drive.free;meter.save()
        if n:
            ref=price174_checkpoint(c,drive,prior["private_data_folder_id"],observed["parent_sha"])
            private_args.resume_file_id,private_args.resume_sha256=ref["file_id"],ref["sha256"]
        return drive
    try:
        # Existing collector/callback output contains private checkpoint refs.
        # Discard it locally rather than publishing or attempting later masking.
        with meter.process_deadline(),c.tempfile.TemporaryFile(mode="w+",encoding="utf-8") as output,\
                redirect_stdout(output),redirect_stderr(output):
            result=cap._collect(private_args,drive_factory=factory,get=meter.perform,
                on_group=lambda drive,state,ref:c.verify_new_group(drive,prior["private_data_folder_id"],state,ref,meter),
                expected_examined=n,external=dict(input_csv=auth["input_csv"],scope=PRICE174_SCOPE))
        c.require(meter.examined==n+batch and meter.checkpoint_sha==result["checkpoint"]["sha256"],
            "CAMPAIGN_BATCH_CLOSURE")
        meter.finish("COMPLETE")
    except c.Refused as exc:
        from tools.twelve_private_capture import SAFE_CODES
        reason=str(exc)
        if reason=="PRICE174_PRIVATE_CHECKPOINT":reason="PRICE_PRIVATE_CHECKPOINT"
        codes=set(SAFE_CODES)|{"CAMPAIGN_DEADLINE","CAMPAIGN_OWNER_OR_SPACE","CAMPAIGN_BATCH_CLOSURE",
            "CAMPAIGN_CHECKPOINT_CHAIN","CAMPAIGN_GROUP_OBJECTS","CAMPAIGN_GROUP_RECEIPT",
            "CAMPAIGN_GROUP_AUTHORITY","CAMPAIGN_GROUP_STATUS","CAMPAIGN_HELD_MARKER",
            "PRICE_PRIVATE_CHECKPOINT","PAGE_BUDGET","BAR_TIMESTAMP","RESUME_ARCHIVE",
            "RESUME_NORMALIZED_FORMAT","RESUME_CHAIN_MEMBERSHIP","RESUME_CHAIN_LIMIT"}
        codes.update("CAMPAIGN_BUDGET_"+k.upper() for k in c.LIMITS)
        if reason not in codes or not c.re.fullmatch("[A-Z_]{1,80}",reason):reason="PRICE_INTERNAL"
        meter.finish("BLOCKED",reason)
        raise c.Refused(reason) from None
    except Exception:
        meter.finish("BLOCKED","PRICE_INTERNAL")
        raise c.Refused("PRICE_INTERNAL") from None
    safe=dict(status="PRICE174_BATCH_VERIFIED",examined_after=meter.examined,rows_verified=meter.rows,
        new_states=dict(meter.states),checkpoint_sha256=meter.checkpoint_sha,source_admission=False,
        pit_verified=False,economic_authority=False)
    print(c.json.dumps(safe,sort_keys=True))
    return safe


def price174_event(c,target,index,kind,payload):
    c.require(target.lock_owned and len(target.entries)>=index-1,"PRICE174_JOURNAL_PREFIX")
    if len(target.entries)==index-1:target.append(kind,**payload)
    entry=target.entries[index-1]
    c.require(entry.get("kind")==kind and {k:entry.get(k) for k in payload}==payload
        and set(entry)==set(payload)|{"sequence","kind","auth_sha256","previous_sha256","recorded_utc"},
        "PRICE174_JOURNAL_CONFLICT")
    path=target.directory/f"{index:06d}.json"
    c.require(not path.is_symlink() and c.bounded_bytes(path)==c.encoded(entry),"PRICE174_JOURNAL_BYTES")
    c.sync_native18_settlement(path)
    return entry


def price174_binding(c,family,journal,auth,budget,state):
    closure=auth["closure_event"]
    c.require(len(family.entries)>=76 and family.entries[75]==closure
        and c.bounded_bytes(family.directory/"000076.json")==c.encoded(closure)
        and c.digest(c.bounded_bytes(family.directory/"000075.json"))==READ392_FAMILY,
        "PRICE174_CLOSURE")
    binding=dict(capture_auth_sha256=price174_hash(c,auth),scope=PRICE174_SCOPE,
        grant_reference_sha256=c.digest(auth["grant_reference"].encode()),closure_sha256=c.digest(c.encoded(closure)),
        budget_state_root=c.os.path.normcase(str(budget)),cohort_state_root=c.os.path.normcase(str(state)))
    entry=price174_event(c,family,77,"PRICE174_COHORT_BOUND",binding)
    price174_event(c,journal,1,"PRICE174_BOUND",dict(binding,family_binding_sha256=c.digest(c.encoded(entry))))


def price174_reconcile(c,family,journal,auth,observed):
    h=price174_hash(c,auth)
    for i,step in enumerate(observed["steps"]):
        run,value=step["run"],step["value"];nonce=run["display_title"][7:]
        fr,jr=78+3*i,2+3*i
        reservation=dict(nonce=nonce,remaining=step["remaining"],active_seconds_remaining=step["active_remaining"],
            parent_checkpoint_sha256=step["parent_sha"],capture_auth_sha256=h,scope=PRICE174_SCOPE)
        # A live run must already have both durable reservations. Never invent
        # permission/reservation after observing an orphan dispatch.
        c.require(len(family.entries)>=fr and len(journal.entries)>=jr,"PRICE174_RESERVATION_MISSING")
        price174_event(c,family,fr,"PRICE174_RESERVED",reservation)
        price174_event(c,journal,jr,"RESERVED",reservation)
        assigned=dict(nonce=nonce,run_id=run["id"],capture_auth_sha256=h)
        price174_event(c,family,fr+1,"PRICE174_RUN_ASSIGNED",assigned)
        price174_event(c,journal,jr+1,"RUN_ASSIGNED",assigned)
        settled=dict(nonce=nonce,run_id=run["id"],capture_auth_sha256=h,
            receipt_sha256=c.digest(c.encoded(value)),checkpoint_sha256=value["checkpoint_sha256"],
            examined=value["examined_after"],usage_delta=value["usage"])
        price174_event(c,journal,jr+2,"SETTLED",settled)
        price174_event(c,family,fr+2,"PRICE174_SETTLED",settled)
    c.require(len(family.entries)==77+3*len(observed["steps"])
        and len(journal.entries)==1+3*len(observed["steps"]),"PRICE174_PENDING")


def price174_forecast(c,observed):
    n=observed["examined"];remaining=174-n
    c.require(n>=128 and observed["receipts"],"PRICE174_FORECAST")
    values=observed["receipts"];counts=[v["examined_after"]-v["examined_before"] for v in values]
    c.require(all(v["status"]=="COMPLETE" and count>0 for v,count in zip(values,counts)),"PRICE174_FORECAST")
    predicted={k:c.math.ceil(max(v["usage"][k]/count for v,count in zip(values,counts))*remaining*1.25)
        for k in c.LIMITS}
    seconds=c.math.ceil(max(t/count for t,count in zip(observed["durations"],counts))*remaining*1.25)
    dispatches=c.math.ceil(remaining/32)
    return dict(estimate_only=True,remaining_subjects=remaining,estimated_usage=predicted,active_seconds=seconds,
        dispatches=dispatches,fits=all(predicted[k]<=observed["remaining"][k] for k in c.LIMITS)
        and observed["active_seconds"]+seconds<=43200 and len(observed["all_runs"])+dispatches<=40)


def price174_progress(c,observed,status):
    return dict(status=status,task_key=PRICE174_TASK,cohort_count=174,examined=observed["examined"],
        new_valid_prices=observed["new_states"]["VALID_COLLECTED"],verified_no_data=observed["new_states"]["VERIFIED_NO_DATA"],
        held=observed["new_states"]["QUARANTINED"],checkpoint_sha256=observed["parent_sha"],
        rows_verified=sum(v["rows_verified"] for v in observed["receipts"]),
        used=observed["used"],remaining=observed["remaining"],active_seconds=observed["active_seconds"],
        active_seconds_remaining=43200-observed["active_seconds"],dispatches=len(observed["all_runs"]),
        dispatches_remaining=40-len(observed["all_runs"]),source_admission=False,pit_verified=False,
        economic_authority=False,total_platform_cost_verified=False)


def price174_host(c,args):
    auth=c.bounded_json(args.price174_authorization,15000);old,names=price174_auth(c,auth)
    c.require(args.budget_state_dir and args.cohort_input
        and c.bounded_bytes(args.cohort_input,8192)==auth["input_csv"].encode()
        and (args.max_batches is None or type(args.max_batches) is int and 1<=args.max_batches<=6)
        and not any(getattr(args,k,None) is not None for k in ("authorization","native_read_control",
            "native18_settle_authorization","native392_settle_control","native392_premeter_control",
            "native392_premeter_publication","native392_run_id","native18_deployed_master","refusal_close_authorization",
            "control_refusal_close_authorization","control_refusal_log","control_refusal_jobs","recovery_run",
            "account_permission_reference","predispatch_recovery","continuation_receipt")),"PRICE174_MODE")
    budget=c.Path(args.budget_state_dir).resolve();state=c.Path(args.state_dir).resolve()
    oldstate=budget.parent/"external-cohort-top500-20261017"
    c.require(state==budget.parent/"external-cohort-sp500-gap-20261020","PRICE174_NAMESPACE")
    named_read_frozen_prefix(c,budget,17,c.CONTINUATION["event"])
    named_read_frozen_prefix(c,oldstate,48,READ392_COHORT)
    price174_closure(c,auth)
    # The old namespace is never reopened for mutation or resumed.
    family=c.external_family_registry(budget,old["authorization"],oldstate);journal=None
    try:
        journal=c.WorkJournal(state,price174_hash(c,auth))
        observed=price174_history(c,auth);started=len(observed["receipts"])
        price174_authority(c,auth,accounting=True)
        if len(family.entries)==76 or not journal.entries:
            c.require(len(family.entries) in {76,77} and not observed["price_runs"],"PRICE174_BINDING_HISTORY")
            price174_authority(c,auth)
            c.require(c.campaign_runs(old["authorization"]["workflow_run_floor"])==observed["all_runs"],
                "PRICE174_CANONICAL_DRIFT")
            branch=c.gh_json(f"repos/{c.REPO}/branches/master")
            c.require(branch.get("protected") is True and branch.get("commit",{}).get("sha")==auth["expected_master"],
                "CAMPAIGN_MASTER_DRIFT")
        price174_binding(c,family,journal,auth,budget,state)
        reported=started
        while True:
            observed=price174_history(c,auth)
            price174_reconcile(c,family,journal,auth,observed)
            if len(observed["receipts"])>reported:
                progress=dict(price174_progress(c,observed,"PRICE174_BATCH_SETTLED"),
                    family_event_sha256=family.parent,cohort_event_sha256=journal.parent,
                    run_id=observed["steps"][-1]["run"]["id"],run_attempt=1,
                    meter_sha256=c.digest(c.encoded(observed["receipts"][-1])))
                c.atomic_json(state/"progress",progress)
                print(c.json.dumps(progress,sort_keys=True),flush=True)
                reported=len(observed["receipts"])
            if observed["terminal_blocked"]:
                return price174_progress(c,observed,"PARTIAL_VERIFIED_STOP")
            if observed["examined"]==174:return price174_progress(c,observed,"COHORT_PROCESSED")
            if len(observed["receipts"])-started>=(args.max_batches or 6):
                return price174_progress(c,observed,"BATCH_BOUNDARY")
            if observed["examined"]>=128:
                forecast=price174_forecast(c,observed)
                print(c.json.dumps(dict(status="PRICE174_128_COST_REVIEW",**forecast),sort_keys=True))
                c.require(forecast["fits"],"CAMPAIGN_CALIBRATION_BUDGET")
            c.require(len(observed["all_runs"])<40 and observed["active_seconds"]+7800<=43200,"CAMPAIGN_DISPATCH_BUDGET")
            proof=price174_authority(c,auth)
            c.require(proof==observed["proof"] and c.campaign_runs(old["authorization"]["workflow_run_floor"])
                ==observed["all_runs"],"PRICE174_CANONICAL_DRIFT")
            nonce=c.PREFIX+c.os.urandom(12).hex()
            control=dict(schema=PRICE174_SCHEMA,authorization=auth,nonce=nonce,parent_sha256=observed["parent_sha"])
            raw=c.encoded(control);c.require(len(raw)<=16384,"CAMPAIGN_CONTROL_SIZE")
            # Current protected tip is the final remote check before reserve/POST.
            branch=c.gh_json(f"repos/{c.REPO}/branches/master")
            c.require(branch.get("protected") is True and branch.get("commit",{}).get("sha")==auth["expected_master"],
                "CAMPAIGN_MASTER_DRIFT")
            reservation=dict(nonce=nonce,remaining=observed["remaining"],
                active_seconds_remaining=43200-observed["active_seconds"],parent_checkpoint_sha256=observed["parent_sha"],
                capture_auth_sha256=price174_hash(c,auth),scope=PRICE174_SCOPE)
            fr,jr=78+3*len(observed["receipts"]),2+3*len(observed["receipts"])
            price174_event(c,family,fr,"PRICE174_RESERVED",reservation)
            price174_event(c,journal,jr,"RESERVED",reservation)
            prior=old["authorization"]
            inputs=dict(private_root_folder_id=prior["private_root_folder_id"],
                private_data_folder_id=prior["private_data_folder_id"],private_research_authorized="true",
                noncommercial_terms_acknowledged="true",end_date="2026-10-14",
                max_new_symbols=str(min(32,174-observed["examined"])),resume_file_id="",
                resume_sha256=observed["parent_sha"],campaign_control=raw.decode(),campaign_nonce=nonce)
            result=c.subprocess.run(["gh","workflow","run",c.WORKFLOW,"--repo",c.REPO,"--ref","master","--json"],
                input=c.json.dumps(inputs).encode(),stdout=c.subprocess.DEVNULL,stderr=c.subprocess.DEVNULL,timeout=45)
            c.require(result.returncode==0,"CAMPAIGN_DISPATCH_UNCERTAIN")
            run=None
            for _ in range(30):
                matches=[r for r in c.campaign_runs(prior["workflow_run_floor"]) if r["display_title"]=="a1-sip "+nonce]
                c.require(len(matches)<=1,"CAMPAIGN_NONCE_REPLAY")
                if matches:run=matches[0];break
                c.time.sleep(2)
            c.require(run is not None,"CAMPAIGN_DISPATCH_UNCERTAIN")
            assigned=dict(nonce=nonce,run_id=run["id"],capture_auth_sha256=price174_hash(c,auth))
            price174_event(c,family,fr+1,"PRICE174_RUN_ASSIGNED",assigned)
            price174_event(c,journal,jr+1,"RUN_ASSIGNED",assigned)
            c.subprocess.run(["gh","run","watch",str(run["id"]),"--repo",c.REPO,"--exit-status","--interval","30"],
                stdout=c.subprocess.DEVNULL,stderr=c.subprocess.DEVNULL,timeout=9000)
    finally:
        try:
            if journal is not None:journal.close()
        finally:family.close()

V6_SOURCE="a20432fad51576309116bf620a60cdcd1503af55"
V6_AUTH="f57d655e7a65c414e5f852b2bdba5fdf331e5c140dbb0dd6b2b12968c7e73a74"
V6_REFERENCE="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6255779963"
V6_PROOF="543884c22789836d91c7357ad6baf897a01a1e30c7db20c115c10d12b6f54033"
REFUSAL_RUN=39171354230
REFUSAL_NONCE="r1000-993-20261015-36b91909388b404d18212948"
REFUSAL_LOG="2d36378133a1e969ff432639230bb25e9a84e38562b53099e3d4ce21fe13e1da"
REFUSAL_SCHEMA="a1-sip-exact-pre-capture-refusal-evidence-v1"
COHORT23="cc9b225a4441af16500e388460b23339e6a9adeb2eaf2139204b8a9911ec9b2f"
FAMILY50="1f73a9b06484bdb3f6e1b39a3c040495e606859106bac4f17fc69d68d539ee89"
BASIS_IDS=[38993769026,38994018637,38994265036,38994543208,38994825057,39021968008,
 39022417378,39022734639,39023083535,39031105199,39031825654,39032304843,39058081878,
 39071437764,39083896869,39084503998,39085031884,39103855450,39137233651,39137963541,39138746776]
V6_PINS={
 ".github/workflows/alpaca_sip_private_backfill_v1.yml":"ec5a081a42f20864bbd8cbb3b9b143c45be15e2c82753de22a7b194dadb9fdea",
 "tools/alpaca_sip_campaign.py":"0c1ab5994ca307a063ea2afc24e4ceb738f167d4a530e423b492c3616ab49d85",
 "tools/alpaca_sip_source_revision.py":"3e79df241b16c1c9130e02b44aff829d3b0cc7f5361605aa19b2b456b19740a2",
 "tools/alpaca_sip_private_backfill_v1.py":"01e94b59f4a587cf54b5bf5b6b25740c7eae8da12358817323d890a379180ec1",
 "tools/configure_macro_research_drive.py":"51c6210ae63f4e7522d5d73d8eb90c5c03348736a9638461772d116fcf51d2fc",
 "tools/macro_history_sources.py":"029ae7337618211c1520adc78c9199831ed739918070c6b29204e9110aa9ab08",
 "tools/twelve_private_capture.py":"2cfe64847cb6a9d4777247968832dbdf5737eafc1ed5f47a2e7b6877bc27bdac"}

V7_SOURCE="0b02c6a0739361ae464162fa2f0f000e94507ce9"
V7_AUTH="e161e75af88243b1220d2677bbac83ef2f6f4a7f36202ce13299d0d3033fc07e"
V7_REFERENCE="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6257183920"
V7_PROOF="1081d182bc2d97ace76dc42ffba226fe686b4bbf63cde0ef2cdcdb35be7695e1"
V7_CLOSURE="b9e74efa8dea224391655d83ed2d1537460e2303b19e2580e9bacb7f805a5d56"
V7_CLOSURE_COMMENT=6257169536
V7_COHORT="11d3c9909e35c81e7b383e535b65a76d1b969c4cc67ee5a721d9e4aa0cbe6482"
V7_FAMILY="d3b2038ef2ffe8202673d37bad8a21f32bf59a6417ef4a119a23b8145ca496d8"
V7_PINS=dict(V6_PINS,**{
 "tools/alpaca_sip_campaign.py":"42d493b2b37a446aabb5e4cf7be160d73f05ae4f18e3ad666a0c8600e9be9e0d",
 "tools/alpaca_sip_source_revision.py":"5c5cf56876600211bea0594987ebbab2b43ef912beb12a5e3c0c91c9381ec495"})
VALIDITY_AUTHORITY="9f0324979fe4acc890c8a3f5365a46281a1be62bb38f9ca54bb556b3de5e5233"
VALIDITY_START="2026-10-19T02:59:53Z"
VALIDITY_END="2026-10-20T02:59:53Z"

V8_SOURCE="961ea35b3f181a896400641ebe273a15bae3b2bd"
V8_AUTH="6e651b15b28180da5c47f5a024c45e695fdf0ebe1b5823f57ecd400a7cf03b08"
V8_REFERENCE="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6259707455"
V8_PROOF="4bd9bd7e37d5e31191200ad9073c8845847ca5dec5564d1852b58d9068ef0a48"
V8_VALIDITY_REFERENCE="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6259704299"
V8_PINS=dict(V7_PINS,**{
 "tools/alpaca_sip_campaign.py":"b0ca0e097f9aebe1ac45267347935b93a510c236cfdb9a09e5db8cf1da13070f",
 "tools/alpaca_sip_source_revision.py":"e349cef5dcd03571d2f8eb475fcdce11b09ea5de53b471322c4ef330ed3c3d2f"})
CONTROL_RUN=39200269684
CONTROL_NONCE="r1000-993-20261015-02ca5e0ce9216525f2cec7f0"
CONTROL_NONCE_SHA="05c4c2a67b0e9a780de4cc2eb9748d21639f51d0e851bf5a7d2823086bad1e71"
CONTROL_LOG="53b73d35027bfed9d33b46160f8d9457db42875f1003e28c326ec3bd34e4468f"
CONTROL_JOBS_RAW="91af4dbaa0ac678b2bafec0cf2a2098c2b687a4bdfd1bf378bcc2021a0011cf9"
CONTROL_JOBS_CANON="500c429ca641c8a167de3667899ad9e0cd4a30a4b851d0d505effdefbc4deb6b"
CONTROL_COHORT28="8afbd092114ec40d979b1decbdc161c666dbc6a5702fc07eb29f817293d38b67"
CONTROL_FAMILY55="cb9546196cff09222012ea0921a314646da25533cdd8f4e15ee76f9a2c7fccda"
CONTROL_COHORT26="6b6650a41c08fefd49f77f14d9b7e5425c3b815712903de16069518c79edbb25"
CONTROL_FAMILY53="53f60f1694f7efbe63405c3e335ab1cff870267cc489173484fb8633f0314aae"
CONTROL_SCHEMA="a1-sip-exact-control-read-refusal-evidence-v1"


def control_corrective(auth):
    return auth.get("schema")=="r1000-sip-external-cohort-authorization-v9"


def control_value(c,scope):
    return dict(schema=CONTROL_SCHEMA,not_runtime_meter=True,run_id=CONTROL_RUN,run_attempt=1,
        auth_sha256=V8_AUTH,source_sha=V8_SOURCE,nonce=CONTROL_NONCE,cohort_scope=scope,
        parent_checkpoint_sha256=CP,checkpoint_sha256=CP,examined_before=128,examined_after=128,
        allowance={k:c.CONTINUED_LIMITS[k]-USED[k] for k in c.LIMITS},usage={k:0 for k in c.LIMITS},
        status="PRE_CAPTURE_REFUSED",reason="EXTERNAL_REFUSAL_LOG",active_seconds=195,
        original_meter_observation="MISSING",failure_log_sha256=CONTROL_LOG,
        terminal_jobs_raw_sha256=CONTROL_JOBS_RAW,terminal_jobs_canonical_sha256=CONTROL_JOBS_CANON,
        original_transport_or_digest_cause="UNKNOWN",zero_io_basis="PINNED_CODE_ORDER_AND_ACTUAL_CONTROL_LOG",
        absence_of_meter_is_zero_io_basis=False,packet_trace_available=False,platform_costs="UNKNOWN_NOT_ZERO")


def verify_control_metadata(c,auth,run,jobs,artifacts,blobs):
    c.require(c.validate_authorization(auth)==V8_AUTH and auth["expected_master"]==V8_SOURCE
        and auth["code_pins"]==V8_PINS,"EXTERNAL_CONTROL_REFUSAL_AUTHORITY")
    c.require(type(run.get("id")) is int and run["id"]==CONTROL_RUN and type(run.get("run_attempt")) is int
        and run["run_attempt"]==1 and run.get("head_sha")==V8_SOURCE and run.get("head_branch")=="master"
        and run.get("event")=="workflow_dispatch" and run.get("display_title")=="a1-sip "+CONTROL_NONCE
        and run.get("status")=="completed" and run.get("conclusion")=="failure"
        and isinstance(run.get("created_at"),str) and c.utc("2026-10-19T04:32:08Z")<=c.utc(run["created_at"])
            <=c.utc("2026-10-19T04:35:58Z") and c.digest(CONTROL_NONCE.encode())==CONTROL_NONCE_SHA,
        "EXTERNAL_CONTROL_REFUSAL_RUN")
    expected=[(117891606529,"offline","success","2026-10-19T04:35:58Z","2026-10-19T04:37:53Z"),
              (117892085699,"capture","failure","2026-10-19T04:37:55Z","2026-10-19T04:39:15Z")]
    c.require(isinstance(jobs,dict) and jobs.get("total_count")==2 and isinstance(jobs.get("jobs"),list)
        and len(jobs["jobs"])==2 and c.digest(c.encoded(jobs))==CONTROL_JOBS_CANON
        and [(j.get("id"),j.get("name"),j.get("conclusion"),j.get("started_at"),j.get("completed_at"))
             for j in jobs["jobs"]]==expected and all(j.get("status")=="completed" for j in jobs["jobs"])
        and artifacts.get("total_count")==0 and artifacts.get("artifacts")==[],"EXTERNAL_CONTROL_REFUSAL_JOBS")
    c.require(set(blobs)==set(V8_PINS) and all(c.digest(blobs[p])==h for p,h in V8_PINS.items()),
              "EXTERNAL_CONTROL_REFUSAL_SOURCE")


def verify_control_jobs(c,jobs,raw):
    c.require(isinstance(raw,bytes) and len(raw)<=1_000_000 and c.digest(raw)==CONTROL_JOBS_RAW,
              "EXTERNAL_CONTROL_REFUSAL_JOBS_RAW")
    retained=c.decode(raw)
    c.require(c.digest(c.encoded(retained))==CONTROL_JOBS_CANON and retained==jobs,
              "EXTERNAL_CONTROL_REFUSAL_JOBS_CANONICAL")
    return retained


def verify_control_failure(c,auth,run,jobs,artifacts,blobs,log,raw_jobs):
    jobs=verify_control_jobs(c,jobs,raw_jobs)
    verify_control_metadata(c,auth,run,jobs,artifacts,blobs)
    c.require(isinstance(log,bytes) and len(log)<=1_000_000 and c.digest(log)==CONTROL_LOG,
              "EXTERNAL_CONTROL_REFUSAL_LOG")
    text=log.decode("utf-8")
    controls=[c.decode(line.split("INPUT_CAMPAIGN_CONTROL: ",1)[1]) for line in text.splitlines()
              if "INPUT_CAMPAIGN_CONTROL: " in line]
    c.require(controls and all(x==controls[0] for x in controls),"EXTERNAL_CONTROL_REFUSAL_CONTROL")
    control=controls[0]
    c.require(set(control)=={"authorization","nonce","preflight_only","recovery_run","external_binding"}
        and c.encoded(control["authorization"])==c.encoded(auth) and control["nonce"]==CONTROL_NONCE
        and control["preflight_only"] is False and control["recovery_run"] is None
        and control["external_binding"]==dict(proof_sha256=V8_PROOF,proof_updated_utc="2026-10-19T04:32:08+00:00",
                                              expires_at_utc=c.utc(VALIDITY_END).isoformat())
        and text.count('{"status": "BLOCKED", "code": "EXTERNAL_REFUSAL_LOG", "source_admission": false}')==1
        and "No artifacts will be uploaded" in text,"EXTERNAL_CONTROL_REFUSAL_CONTROL")
    # Positive execution witness, not an inference from the absent artifact:
    # exact deployed bytes + actual control/error body + the published call order.
    import ast
    tree=ast.parse(blobs["tools/alpaca_sip_campaign.py"].decode("utf-8"))
    worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="external_worker")
    history=[n.lineno for n in ast.walk(worker) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
             and n.func.id=="external_history"]
    meters=[n.lineno for n in ast.walk(worker) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
            and n.func.id=="RuntimeMeter"]
    c.require(len(history)==len(meters)==1 and history[0]<meters[0],"EXTERNAL_CONTROL_REFUSAL_IO_BOUNDARY")
    return control_value(c,auth["external_cohort"]["scope"])


def human_record(c,comment,tag,*,window=None):
    start,end=window if window is not None else (VALIDITY_START,VALIDITY_END)
    c.require(isinstance(comment,dict) and type(comment.get("id")) is int and comment["id"]>0
        and comment.get("issue_url")==f"https://api.github.com/repos/{c.REPO}/issues/448"
        and comment.get("author_association")=="OWNER" and comment.get("user",{}).get("type")=="User"
        and type(comment["user"].get("id")) is int and comment["user"]["id"]>0
        and isinstance(comment.get("body"),str) and isinstance(comment.get("created_at"),str)
        and comment["created_at"]==comment.get("updated_at")
        and c.utc(start)<=c.utc(comment["created_at"])<=c.utc()
        and c.utc(comment["created_at"])<c.utc(end),"EXTERNAL_CONTROL_REFUSAL_OWNER")
    lines=[line[len(tag):] for line in comment["body"].splitlines() if line.startswith(tag)]
    c.require(len(lines)==1 and len(lines[0])<=4096,"EXTERNAL_CONTROL_REFUSAL_OWNER")
    proof=dict(reference=f"https://github.com/{c.REPO}/issues/448#issuecomment-{comment['id']}",
        comment_id=comment["id"],author_id=comment["user"]["id"],created_at=comment["created_at"],
        body_sha256=c.digest(comment["body"].encode()))
    return c.decode(lines[0]),proof


def control_grant_record(c,source,pins,scope):
    c.require(isinstance(source,str) and c.re.fullmatch(r"[0-9a-f]{40}",source) and source!=V8_SOURCE
        and set(pins)==set(V8_PINS) and all(isinstance(v,str) and c.re.fullmatch(r"[0-9a-f]{64}",v)
        for v in pins.values()),"EXTERNAL_CONTROL_REFUSAL_SOURCE")
    return dict(schema="a1-sip-exact-control-read-refusal-grant-v1",source_sha=source,
        code_pins_sha256=c.digest(c.encoded(pins)),old_auth_sha256=V8_AUTH,old_source_sha=V8_SOURCE,
        old_code_pins_sha256=c.digest(c.encoded(V8_PINS)),old_proof_sha256=V8_PROOF,
        human_authority_sha256=VALIDITY_AUTHORITY,not_before_utc=VALIDITY_START,expires_at_utc=VALIDITY_END,
        old_refusal_seal_sha256=V7_CLOSURE,original_log_canonical_sha256=REFUSAL_LOG,
        control_refusal_evidence_sha256=c.digest(c.encoded(control_value(c,scope))),
        run_id=CONTROL_RUN,run_attempt=1,nonce_sha256=CONTROL_NONCE_SHA,failure_log_sha256=CONTROL_LOG,
        terminal_jobs_raw_sha256=CONTROL_JOBS_RAW,terminal_jobs_canonical_sha256=CONTROL_JOBS_CANON,
        cohort28_sha256=CONTROL_COHORT28,family55_sha256=CONTROL_FAMILY55,
        prior_cohort26_sha256=CONTROL_COHORT26,prior_family53_sha256=CONTROL_FAMILY53,
        actual_job_seconds=195,actual_dispatches=1,not_runtime_meter=True,original_missing_meter_preserved=True,
        original_failure_cause="UNKNOWN",io_nonentry_basis="PINNED_CODE_ORDER_AND_ACTUAL_CONTROL_LOG",
        absence_of_meter_is_zero_io_basis=False,limits=c.CONTINUED_LIMITS,active_limit_seconds=43200,
        dispatch_limit=40,unknown_storage_bytes_still_charged=302101,platform_costs="UNKNOWN_NOT_ZERO")


def control_payload(c,source,pins,scope,grant):
    value,proof=human_record(c,grant,"A1_SIP_CONTROL_READ_REFUSAL_AUTHORIZATION ")
    c.require(value==control_grant_record(c,source,pins,scope),"EXTERNAL_CONTROL_REFUSAL_GRANT")
    return dict(schema="a1-sip-exact-control-read-refusal-closed-v1",run_id=CONTROL_RUN,run_attempt=1,
        nonce=CONTROL_NONCE,capture_auth_sha256=V8_AUTH,scope=scope,
        control_refusal_evidence_sha256=value["control_refusal_evidence_sha256"],
        grant_reference=proof["reference"],grant_proof_sha256=c.digest(c.encoded(proof)),
        grant_created_at=proof["created_at"],grant_author_id=proof["author_id"],source_sha=source,
        code_pins_sha256=c.digest(c.encoded(pins)),actual_job_seconds=195,actual_dispatches=1,
        meter_observation="MISSING",not_runtime_meter=True,original_failure_cause="UNKNOWN",
        platform_costs="UNKNOWN_NOT_ZERO")


def control_closure_entry(c,payload,clock,family=False):
    c.require(isinstance(clock,str) and c.utc(payload["grant_created_at"])<=c.utc(clock)<=c.utc()
        and c.utc(VALIDITY_START)<=c.utc(clock)<c.utc(VALIDITY_END),"EXTERNAL_CONTROL_REFUSAL_CLOCK")
    return dict(sequence=56 if family else 29,kind="CONTROL_READ_REFUSAL_CLOSED",
        auth_sha256=c.external_family_genesis() if family else V8_AUTH,
        previous_sha256=CONTROL_FAMILY55 if family else CONTROL_COHORT28,recorded_utc=clock,**payload)


def verify_control_parent(c,auth,state,used,active,runs,proofs):
    c.require(control_corrective(auth) and state["examined"]==128 and state["parent"]==CP
        and used==USED and active==5318 and state["receipts"][-1]==control_value(c,auth["external_cohort"]["scope"])
        and [r["id"] for r in runs]==BASIS_IDS+[REFUSAL_RUN,CONTROL_RUN]
        and proofs.get(V8_AUTH,{}).get("proof_sha256")==V8_PROOF,"EXTERNAL_CONTROL_SOURCE_PARENT")


def control_source_binding(c,auth,proof,receipt):
    return dict(schema="a1-sip-exact-control-read-source-bound-v1",prior_auth_sha256=V8_AUTH,
        prior_source_sha=V8_SOURCE,prior_proof_sha256=V8_PROOF,closed_run_id=CONTROL_RUN,
        closure_sha256=c.digest(c.encoded(receipt)),cohort29_sha256=receipt["cohort_event"]["sha256"],
        family56_sha256=receipt["family_event"]["sha256"],checkpoint_sha256=CP,used=USED,
        active_seconds=5318,dispatches=23,validity_authority_sha256=VALIDITY_AUTHORITY,
        validity_not_before_utc=VALIDITY_START,validity_expires_at_utc=VALIDITY_END,
        new_auth_sha256=c.validate_authorization(auth),new_source_sha=auth["expected_master"],
        new_code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),**proof)


def verify_control_source_entry(c,entry,expected,receipt,family=False):
    key="family_event" if family else "cohort_event"
    c.require(set(entry)=={"sequence","kind","auth_sha256","previous_sha256","recorded_utc"}|set(expected)
        and type(entry["sequence"]) is int and entry["sequence"]==(57 if family else 30)
        and entry["kind"]=="CONTROL_SOURCE_BOUND"
        and entry["auth_sha256"]==(c.external_family_genesis() if family else expected["new_auth_sha256"])
        and entry["previous_sha256"]==receipt[key]["sha256"]
        and all(entry[k]==v for k,v in expected.items()) and isinstance(entry["recorded_utc"],str)
        and c.utc(receipt[key]["recorded_utc"])<=c.utc(expected["proof_updated_utc"])<=c.utc(entry["recorded_utc"])<=c.utc()
        and c.utc(VALIDITY_START)<=c.utc(entry["recorded_utc"])<c.utc(VALIDITY_END)
        and c.utc(expected["expires_at_utc"])==c.utc(VALIDITY_END),"EXTERNAL_CONTROL_SOURCE_BINDING")


def verify_control_closure(c,auth,receipt,grant,seal):
    sr=auth["external_cohort"]["source_revision"]
    value,proof=human_record(c,seal,"A1_SIP_CONTROL_READ_REFUSAL_CLOSED ")
    c.require(proof["reference"]==sr["control_refusal_reference"] and value==receipt
        and c.digest(c.encoded(receipt))==sr["control_refusal_sha256"]
        and set(receipt)=={"schema","payload","cohort_event","family_event"}
        and receipt["schema"]=="a1-sip-exact-control-read-refusal-receipt-v1","EXTERNAL_CONTROL_REFUSAL_RECEIPT")
    payload=control_payload(c,auth["expected_master"],auth["code_pins"],auth["external_cohort"]["scope"],grant)
    c.require(receipt["payload"]==payload and proof["author_id"]==payload["grant_author_id"],
              "EXTERNAL_CONTROL_REFUSAL_RECEIPT")
    for key,family in (("cohort_event",False),("family_event",True)):
        event=receipt[key]
        c.require(set(event)=={"recorded_utc","sha256"} and c.digest(c.encoded(control_closure_entry(
            c,payload,event["recorded_utc"],family)))==event["sha256"]
            and c.utc(event["recorded_utc"])<=c.utc(proof["created_at"]),"EXTERNAL_CONTROL_REFUSAL_RECEIPT")
    c.require(c.utc(receipt["cohort_event"]["recorded_utc"])<=c.utc(receipt["family_event"]["recorded_utc"]),
              "EXTERNAL_CONTROL_REFUSAL_RECEIPT")
    return receipt


def renewed(auth):
    return auth.get("schema") in ("r1000-sip-external-cohort-authorization-v8","r1000-sip-external-cohort-authorization-v9")


def bind_control_revision(c,journal,family,auth,observed):
    receipt=journal.control_closure;expected=journal.control_revision
    c.require(control_corrective(auth) and expected==control_source_binding(c,auth,observed['external_proof'],receipt),
              "EXTERNAL_CONTROL_SOURCE_BINDING")
    if len(journal.entries)==29 or len(family.entries)==56:
        require_window(c,auth)
        verify_control_parent(c,auth,dict(examined=observed['examined'],parent=observed['parent_sha'],
            receipts=observed['cohort_receipts']),observed['used'],observed['active_seconds'],observed['runs'],observed['epoch_proofs'])
    family.control_revision,family.control_closure=expected,receipt
    for target,is_family,slot,key in ((journal,False,29,'cohort_event'),(family,True,56,'family_event')):
        c.require(len(target.entries)>=slot and target.entries[slot-1]==control_closure_entry(c,
            receipt['payload'],receipt[key]['recorded_utc'],is_family),"EXTERNAL_CONTROL_REFUSAL_RECEIPT")
        c.sync_native18_settlement(target.directory/f'{slot:06d}.json')
        if len(target.entries)==slot:
            c.external_deployed(auth)
            target.append('CONTROL_SOURCE_BOUND',**expected)
        entry=target.entries[slot];verify_control_source_entry(c,entry,expected,receipt,is_family)
        path=target.directory/f'{slot+1:06d}.json'
        c.require(c.bounded_bytes(path)==c.encoded(entry),"EXTERNAL_CONTROL_SOURCE_BINDING")
        c.sync_native18_settlement(path)


def append_control_closure(c,journal,family,payload):
    """Only this exact retained28/55 pair; a crash resumes the same append."""
    c.require(len(journal.entries) in (28,29) and len(family.entries) in (55,56)
        and (len(family.entries)!=56 or len(journal.entries)==29)
        and c.digest(c.bounded_bytes(journal.directory/'000028.json'))==CONTROL_COHORT28
        and c.digest(c.bounded_bytes(family.directory/'000055.json'))==CONTROL_FAMILY55
        and c.digest(c.bounded_bytes(journal.directory/'000026.json'))==CONTROL_COHORT26
        and c.digest(c.bounded_bytes(family.directory/'000053.json'))==CONTROL_FAMILY53,
        'EXTERNAL_CONTROL_REFUSAL_PREFIX')
    receipt=dict(schema='a1-sip-exact-control-read-refusal-receipt-v1',payload=payload)
    for target,is_family,slot,key in ((journal,False,29,'cohort_event'),(family,True,56,'family_event')):
        if len(target.entries)==slot-1:target.append('CONTROL_READ_REFUSAL_CLOSED',**payload)
        entry=target.entries[slot-1]
        c.require(entry==control_closure_entry(c,payload,entry['recorded_utc'],is_family),'EXTERNAL_CONTROL_REFUSAL_RECEIPT')
        path=target.directory/f'{slot:06d}.json'
        c.require(c.bounded_bytes(path)==c.encoded(entry),'EXTERNAL_CONTROL_REFUSAL_RECEIPT')
        c.sync_native18_settlement(path)
        receipt[key]=dict(recorded_utc=entry['recorded_utc'],sha256=c.digest(c.bounded_bytes(path)))
    c.require(c.utc(receipt['cohort_event']['recorded_utc'])<=c.utc(receipt['family_event']['recorded_utc']),
              'EXTERNAL_CONTROL_REFUSAL_CLOCK')
    return receipt


def control_accounting_host(c,args):
    """Explicit exact-run bookkeeping; never creates a consent or dispatch."""
    auth=c.bounded_json(args.authorization,15000);grant=c.bounded_json(args.control_refusal_close_authorization,4096)
    c.require(c.validate_authorization(auth)==V8_AUTH and set(grant)=={'source_sha','code_pins','grant_reference'}
        and args.control_refusal_log and args.control_refusal_jobs and args.budget_state_dir and args.cohort_input and args.predispatch_recovery
        and not any((args.refusal_close_authorization,args.recovery_run,args.max_batches,args.account_permission_reference,
                     args.continuation_receipt,args.native18_deployed_master)),'EXTERNAL_CONTROL_REFUSAL_ACCOUNTING')
    c.external_deployed(dict(expected_master=grant['source_sha'],code_pins=grant['code_pins']))
    ref=grant['grant_reference']
    c.require(isinstance(ref,str) and c.re.fullmatch(
        r'https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+',ref),'EXTERNAL_CONTROL_REFUSAL_GRANT')
    comment=c.gh_json(f"repos/{c.REPO}/issues/comments/{int(ref.rsplit('-',1)[1])}")
    payload=control_payload(c,grant['source_sha'],grant['code_pins'],auth['external_cohort']['scope'],comment)
    require_window(c,auth)
    c.require(c.bounded_bytes(args.cohort_input,8192)==auth['external_cohort']['input_csv'].encode(),'EXTERNAL_COHORT_HASH')
    budget=c.Path(args.budget_state_dir).resolve();state=c.Path(args.state_dir).resolve()
    c.require(budget.is_dir() and state.is_dir() and not state.is_symlink() and state==budget.parent/(
        'external-cohort-'+auth['external_cohort']['scope']['namespace']),'EXTERNAL_NAMESPACE')
    recovery=c.local_reject_recovery(args.predispatch_recovery,auth['external_cohort']['prior_authorization'],budget)
    global_journal=c.WorkJournal(budget,c.CONTINUATION['auth'],recovery=recovery);family=journal=None
    try:
        c.verify_external_budget_journal(global_journal,auth,recovery)
        observed=c.external_history(auth,allow_stopped=True,enforce_expiry=False,control_accounting_log=args.control_refusal_log,
                                    control_accounting_jobs=args.control_refusal_jobs)
        family=c.external_family_registry(budget,auth,state)
        journal=c.external_journal(state,auth,observed['external_proof'],epoch_proofs=observed['epoch_proofs'])
        global_journal.reconcile(observed['runs'][:5]);journal.reconcile(observed['cohort_runs'])
        # Reopening a partially durable closure validates both original prefixes
        # before rebuilding its exact payload and clock; never a fresh nonce.
        if len(journal.entries)==28 and len(family.entries)==55:
            c.require(c.reconcile_external_family(family,journal,auth,observed,control_accounting=True)==CONTROL_NONCE,
                      'EXTERNAL_CONTROL_REFUSAL_PREFIX')
        c.require(c.external_proof(auth)==observed['external_proof'] and observed['external_proof']['proof_sha256']==V8_PROOF
            and c.campaign_runs(auth['workflow_run_floor'])==observed['runs'],'EXTERNAL_CANONICAL_DRIFT')
        c.external_deployed(dict(expected_master=grant['source_sha'],code_pins=grant['code_pins']))
        receipt=append_control_closure(c,journal,family,payload)
        journal.control_closure=receipt
        c.require(c.reconcile_external_family(family,journal,auth,observed,control_accounting=True) is None,
                  'EXTERNAL_CONTROL_REFUSAL_PREFIX')
        path=c.Path(args.control_refusal_close_authorization).resolve().with_name('CONTROL_REFUSAL_CLOSURE_RECEIPT.private.json')
        c.require(all(p not in path.parents for p in (budget,state,family.directory)),'EXTERNAL_CONTROL_REFUSAL_PATH')
        raw=c.encoded(receipt)
        if path.exists():c.require(c.bounded_bytes(path)==raw,'EXTERNAL_CONTROL_REFUSAL_RECEIPT')
        else:
            with path.open('xb') as f:f.write(raw);f.flush();c.os.fsync(f.fileno())
        c.sync_native18_settlement(path)
        return dict(status='EXACT_CONTROL_READ_REFUSAL_CLOSED',receipt_sha256=c.digest(raw),
            actual_active_seconds=5318,actual_dispatches=23,new_price_subjects=0,original_meter_observation='MISSING',
            original_failure_cause='UNKNOWN',not_runtime_meter=True)
    finally:
        try:
            if journal is not None:journal.close()
        finally:
            try:
                if family is not None:family.close()
            finally:global_journal.close()


def corrective(auth):
    return renewed(auth) or auth.get("schema")=="r1000-sip-external-cohort-authorization-v7"


def corrective_auth(c,auth):
    if control_corrective(auth):return corrective_auth(c,previous(c,auth))
    return previous(c,auth) if renewed(auth) else auth


def expiry(c,auth):
    return c.utc(VALIDITY_END) if renewed(auth) else c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48)


def require_window(c,auth):
    c.require((not renewed(auth) or c.utc(VALIDITY_START)<=c.utc()) and c.utc()<expiry(c,auth),"CAMPAIGN_EXPIRED")


def validity_record(c,source,pins,scope):
    c.require(isinstance(source,str) and c.re.fullmatch(r"[0-9a-f]{40}",source)
        and source not in (V7_SOURCE,V6_SOURCE) and set(pins)==set(V7_PINS)
        and all(isinstance(v,str) and c.re.fullmatch(r"[0-9a-f]{64}",v) for v in pins.values()),"EXTERNAL_VALIDITY_SOURCE")
    return dict(schema="a1-sip-fixed-human24h-validity-v1",human_authority_sha256=VALIDITY_AUTHORITY,
        human_turn_id="01a15219-ef57-7270-a8df-8267e3c2fdcd",human_message_id="01a15219-f006-7632-ab4a-2dc8adc12313",
        not_before_utc=VALIDITY_START,expires_at_utc=VALIDITY_END,original_first_utc=c.CONTINUATION["first"],
        original_expiry_utc=(c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48)).isoformat(),
        prior_auth_sha256=V7_AUTH,prior_source_sha=V7_SOURCE,prior_proof_sha256=V7_PROOF,
        prior_code_pins_sha256=c.digest(c.encoded(V7_PINS)),refusal_closure_sha256=V7_CLOSURE,
        cohort25_sha256=V7_COHORT,family52_sha256=V7_FAMILY,checkpoint_sha256=CP,
        used=USED,active_seconds=5123,dispatches=22,limits=c.CONTINUED_LIMITS,active_limit=43200,dispatch_limit=40,
        scope=scope,new_source_sha=source,new_code_pins_sha256=c.digest(c.encoded(pins)),
        prospective_only=True,automatic_extension=False,budget_reset=False,unknown_storage_bytes_still_charged=302101,
        platform_costs="UNKNOWN_NOT_ZERO",past_download_failure_cause="UNKNOWN")


def verify_validity_grant(c,auth,comment):
    ref=auth["external_cohort"]["source_revision"]["validity_reference"]
    tag="A1_SIP_HUMAN24H_VALIDITY "
    c.require(type(comment.get("id")) is int and ref==f"https://github.com/{c.REPO}/issues/448#issuecomment-{comment['id']}"
        and comment.get("issue_url")==f"https://api.github.com/repos/{c.REPO}/issues/448"
        and comment.get("author_association")=="OWNER" and comment.get("user",{}).get("type")=="User"
        and type(comment["user"].get("id")) is int and comment["user"]["id"]>0
        and isinstance(comment.get("body"),str) and isinstance(comment.get("created_at"),str)
        and comment["created_at"]==comment.get("updated_at")
        and c.utc(VALIDITY_START)<=c.utc(comment["created_at"])<=c.utc()
        and c.utc(comment["created_at"])<c.utc(VALIDITY_END),"EXTERNAL_VALIDITY_GRANT")
    lines=[line[len(tag):] for line in comment["body"].splitlines() if line.startswith(tag)]
    c.require(len(lines)==1 and len(lines[0])<=4096 and c.decode(lines[0])==validity_record(
        c,auth["expected_master"],auth["code_pins"],auth["external_cohort"]["scope"]),"EXTERNAL_VALIDITY_GRANT")
    return dict(reference=ref,comment_id=comment["id"],author_id=comment["user"]["id"],
        created_at=comment["created_at"],updated_at=comment["updated_at"],body_sha256=c.digest(comment["body"].encode()))


def validity_binding(c,auth,proof,grant):
    return dict(schema="a1-sip-human24h-validity-bound-v1",prior_auth_sha256=V7_AUTH,prior_source_sha=V7_SOURCE,
        prior_proof_sha256=V7_PROOF,prior_cohort25_sha256=V7_COHORT,prior_family52_sha256=V7_FAMILY,
        authority_sha256=VALIDITY_AUTHORITY,not_before_utc=VALIDITY_START,new_expiry_utc=VALIDITY_END,
        grant_proof_sha256=c.digest(c.encoded(grant)),grant_reference=grant["reference"],
        checkpoint_sha256=CP,used=USED,active_seconds=5123,dispatches=22,
        new_auth_sha256=c.validate_authorization(auth),new_source_sha=auth["expected_master"],
        new_code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),**proof)


def verify_validity_entry(c,entry,expected,family=False):
    c.require(set(entry)=={"sequence","kind","auth_sha256","previous_sha256","recorded_utc"}|set(expected)
        and entry["sequence"]==(53 if family else 26) and entry["kind"]=="VALIDITY_SOURCE_BOUND"
        and entry["auth_sha256"]==(c.external_family_genesis() if family else expected["new_auth_sha256"])
        and entry["previous_sha256"]==(V7_FAMILY if family else V7_COHORT)
        and all(entry[k]==v for k,v in expected.items()) and isinstance(entry["recorded_utc"],str)
        and c.utc(VALIDITY_START)<=c.utc(expected["proof_updated_utc"])<=c.utc(entry["recorded_utc"])<=c.utc()
        and c.utc(entry["recorded_utc"])<c.utc(VALIDITY_END)
        and c.utc(expected["expires_at_utc"])==c.utc(VALIDITY_END),"EXTERNAL_VALIDITY_BINDING")


def verify_validity_parent(c,auth,state,used,active,prior_runs,proofs):
    verify_correction_state(c,state,used,active)
    c.require(renewed(auth) and [r["id"] for r in prior_runs]==BASIS_IDS+[REFUSAL_RUN]
        and proofs.get(V7_AUTH,{}).get("proof_sha256")==V7_PROOF,"EXTERNAL_VALIDITY_PARENT")


def verify_validity_run(c,auth,run,proof,value=None):
    if not renewed(auth):return
    c.require(isinstance(run.get("created_at"),str)
        and c.utc(VALIDITY_START)<=c.utc(proof["proof_updated_utc"])<=c.utc(run["created_at"])<=c.utc()
        and c.utc(run["created_at"])<c.utc(VALIDITY_END),"EXTERNAL_VALIDITY_RUN_CLOCK")
    if value is not None:
        c.require(value.get("validity_authority_sha256")==VALIDITY_AUTHORITY
            and value.get("validity_not_before_utc")==VALIDITY_START
            and value.get("validity_expires_at_utc")==VALIDITY_END,"EXTERNAL_VALIDITY_RECEIPT")


def revision_recovery(c,auth,state,version,transitions,used,active,prior_runs,proofs):
    c.require(state["version"]<=version<=state["version"]+1 or renewed(auth)
        and state["version"]==2 and version==4,"EXTERNAL_AUTH_REVISION_ORDER")
    expected=None
    if version>state["version"]:
        transition=transitions[version-1]
        if transition.get("kind")=="SOURCE_REVISION":verify_transition(c,state,used,active)
        elif transition.get("kind")=="CORRECTIVE_SOURCE":verify_correction_state(c,state,used,active)
        elif transition.get("kind")=="VALIDITY_SOURCE":verify_validity_parent(c,auth,state,used,active,prior_runs,proofs)
        elif transition.get("kind")=="CONTROL_SOURCE":verify_control_parent(c,auth,state,used,active,prior_runs,proofs)
        else:
            c.require(transition["run_id"] in state["named_failures"] and state["examined"]==transition["examined"]
                and state["parent"]==transition["checkpoint_sha256"],"EXTERNAL_RECOVERY_PARENT")
            expected=transition["run_id"]
    elif version<len(transitions):
        c.require(transitions[version].get("kind") in ("SOURCE_REVISION","CORRECTIVE_SOURCE","VALIDITY_SOURCE","CONTROL_SOURCE")
            or transitions[version]["run_id"] not in state["named_failures"],"EXTERNAL_AUTH_REVISION_ORDER")
    return expected


def refusal_value(c,scope):
    return dict(schema=REFUSAL_SCHEMA,not_runtime_meter=True,run_id=REFUSAL_RUN,run_attempt=1,
        auth_sha256=V6_AUTH,source_sha=V6_SOURCE,nonce=REFUSAL_NONCE,cohort_scope=scope,
        parent_checkpoint_sha256=CP,checkpoint_sha256=CP,examined_before=128,examined_after=128,
        allowance={k:c.CONTINUED_LIMITS[k]-USED[k] for k in c.LIMITS},usage={k:0 for k in c.LIMITS},
        status="PRE_CAPTURE_REFUSED",reason="EXTERNAL_TIME_FORECAST_ACCEPTANCE",active_seconds=185,
        original_meter_observation="MISSING",log_sha256=REFUSAL_LOG,platform_costs="UNKNOWN_NOT_ZERO")


def is_refusal(value):
    return isinstance(value,dict) and value.get("schema") in (REFUSAL_SCHEMA,CONTROL_SCHEMA)


def price_observations(c,auth,observed):
    receipts,durations=observed["cohort_receipts"],observed["cohort_durations"]
    c.require(len(receipts)==len(durations),"EXTERNAL_FORECAST_SAMPLE")
    if not corrective(auth):
        c.require(not any(is_refusal(r) for r in receipts),"EXTERNAL_REFUSAL_EVIDENCE")
        return receipts,durations
    refs=[(r,t) for r,t in zip(receipts,durations) if is_refusal(r)]
    expected=[(refusal_value(c,auth["external_cohort"]["scope"]),185)]
    if control_corrective(auth):expected.append((control_value(c,auth["external_cohort"]["scope"]),195))
    c.require(refs==expected,"EXTERNAL_REFUSAL_EVIDENCE")
    pairs=[(r,t) for r,t in zip(receipts,durations) if not is_refusal(r)]
    return [r for r,t in pairs],[t for r,t in pairs]


def calibration_basis(c,auth,observed):
    runs=observed["runs"];current=observed.get("current_run")
    current_nonce=observed.get("current_nonce")
    prior_count=23 if control_corrective(auth) else 22 if corrective(auth) else 21
    c.require(len(runs)==prior_count+(current is not None)
        and [r["id"] for r in runs[:21]]==BASIS_IDS,"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    if corrective(auth):
        r=runs[21]
        c.require(r.get("id")==REFUSAL_RUN and r.get("run_attempt")==1 and r.get("head_sha")==V6_SOURCE
            and r.get("display_title")=="a1-sip "+REFUSAL_NONCE and r.get("status")=="completed"
            and r.get("conclusion")=="failure" and observed["active_seconds"]==(5318 if control_corrective(auth) else 5123),
            "EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    else:
        c.require(observed["active_seconds"]==4938,"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    if control_corrective(auth):
        r=runs[22]
        c.require(r.get("id")==CONTROL_RUN and r.get("run_attempt")==1 and r.get("head_sha")==V8_SOURCE
            and r.get("display_title")=="a1-sip "+CONTROL_NONCE and r.get("status")=="completed"
            and r.get("conclusion")=="failure","EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    if current is not None:
        r=runs[-1]
        c.require(isinstance(observed.get("external_proof"),dict)
            and isinstance(observed["external_proof"].get("proof_updated_utc"),str),"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
        c.require(type(current) is int and current>0 and current not in BASIS_IDS+[REFUSAL_RUN,CONTROL_RUN]
                if corrective(auth) else type(current) is int and current==REFUSAL_RUN,
                "EXTERNAL_TIME_FORECAST_ACCEPTANCE")
        c.require(r.get("id")==current and r.get("run_attempt")==1 and r.get("head_sha")==auth["expected_master"]
            and isinstance(current_nonce,str) and c.re.fullmatch(c.PREFIX+r"[0-9a-f]{24}",current_nonce)
            and r.get("display_title")=="a1-sip "+current_nonce and r.get("status")=="in_progress"
            and r.get("conclusion") is None and isinstance(r.get("created_at"),str)
            and c.utc(observed["external_proof"]["proof_updated_utc"])<=c.utc(r["created_at"])<=c.utc(),
            "EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    receipts,durations=price_observations(c,auth,observed)
    return dict(runs=runs[:21],active_seconds=4938,cohort_receipts=receipts,cohort_durations=durations)


def verify_refusal_metadata(c,auth,run,jobs,artifacts,source_blobs):
    c.require(c.validate_authorization(auth)==V6_AUTH and auth["code_pins"]==V6_PINS,
              "EXTERNAL_REFUSAL_AUTHORITY")
    c.require(type(run.get("id")) is int and run["id"]==REFUSAL_RUN and run.get("run_attempt")==1
        and run.get("head_sha")==V6_SOURCE and run.get("display_title")=="a1-sip "+REFUSAL_NONCE
        and run.get("status")=="completed" and run.get("conclusion")=="failure"
        and run.get("created_at")=="2026-10-18T22:14:28Z","EXTERNAL_REFUSAL_RUN")
    expected=[(117804908535,"offline","success","2026-10-18T22:14:31Z","2026-10-18T22:16:13Z"),
              (117805290762,"capture","failure","2026-10-18T22:16:16Z","2026-10-18T22:17:39Z")]
    c.require(jobs.get("total_count")==2 and len(jobs.get("jobs",[]))==2
        and [(j.get("id"),j.get("name"),j.get("conclusion"),j.get("started_at"),j.get("completed_at"))
             for j in jobs["jobs"]]==expected and all(j.get("status")=="completed" for j in jobs["jobs"])
        and artifacts.get("total_count")==0 and artifacts.get("artifacts")==[],"EXTERNAL_REFUSAL_JOBS")
    c.require(set(source_blobs)==set(V6_PINS)
        and all(c.digest(source_blobs[p])==h for p,h in V6_PINS.items()),"EXTERNAL_REFUSAL_SOURCE")
    return refusal_value(c,auth["external_cohort"]["scope"])


def control_log_error(c,reason,returncode,byte_count,canonical_sha256=None,http_status=None):
    error=c.Refused("EXTERNAL_REFUSAL_LOG_"+reason)
    error.control_read_diagnostic=dict(schema="a1-safe-control-read-failure-v1",
        category="GITHUB_HISTORICAL_REFUSAL_LOG",reason=reason,returncode=returncode,
        stdout_bytes=byte_count,canonical_sha256=canonical_sha256,http_status=http_status,
        target_run_id=REFUSAL_RUN,target_job_id=117805290762,expected_canonical_sha256=REFUSAL_LOG)
    return error


def canonical_refusal_log(c,log,returncode=0):
    c.require(isinstance(log,bytes),"EXTERNAL_REFUSAL_LOG_REPRESENTATION")
    if len(log)>1_000_000:raise control_log_error(c,"OVERSIZE",returncode,len(log))
    canonical=log.replace(b"\r\n",b"\n").rstrip(b"\n")+b"\n\n"
    if c.digest(canonical)!=REFUSAL_LOG:
        raise control_log_error(c,"DIGEST",returncode,len(log),c.digest(canonical))
    return canonical


def refusal_log_result(c,result):
    c.require(type(result.returncode) is int and isinstance(result.stdout,bytes),"EXTERNAL_REFUSAL_LOG_REPRESENTATION")
    if result.returncode:
        # The production invocation discards stderr before buffering. Its HTTP
        # status was not observed; never infer it from a later/caller response.
        raise control_log_error(c,"TRANSPORT",result.returncode,len(result.stdout),http_status=None)
    canonical_refusal_log(c,result.stdout,result.returncode)
    return result.stdout


def verify_sealed_refusal(c,auth,run,jobs,artifacts,source_blobs,receipt,prior_proof):
    prior=corrective_auth(c,auth)
    c.require(c.validate_authorization(prior)==V7_AUTH and prior_proof.get("proof_sha256")==V7_PROOF
        and c.digest(c.encoded(receipt))==V7_CLOSURE
        and receipt["payload"]["source_sha"]==V7_SOURCE
        and receipt["payload"]["code_pins_sha256"]==c.digest(c.encoded(V7_PINS)),"EXTERNAL_SEALED_REFUSAL")
    old=previous(c,prior)
    value=verify_refusal_metadata(c,old,run,jobs,artifacts,source_blobs)
    c.require(value["log_sha256"]==REFUSAL_LOG
        and receipt["payload"]["refusal_evidence_sha256"]==c.digest(c.encoded(value)),"EXTERNAL_SEALED_REFUSAL")
    return value


def verify_refusal(c,auth,run,jobs,artifacts,source_blobs,log):
    verify_refusal_metadata(c,auth,run,jobs,artifacts,source_blobs)
    # Preserve the exact BOM-bearing canonical hash; this is not a packet trace.
    canonical=canonical_refusal_log(c,log)
    text=canonical.decode("utf-8")
    controls=[c.decode(line.split("INPUT_CAMPAIGN_CONTROL: ",1)[1]) for line in text.splitlines()
              if "INPUT_CAMPAIGN_CONTROL: " in line]
    c.require(controls and all(x==controls[0] for x in controls),"EXTERNAL_REFUSAL_CONTROL")
    control=controls[0]
    c.require(set(control)=={"authorization","nonce","preflight_only","recovery_run","external_binding"}
        and c.encoded(control["authorization"])==c.encoded(auth) and control["nonce"]==REFUSAL_NONCE
        and control["preflight_only"] is False and control["recovery_run"] is None
        and control["external_binding"]==dict(proof_sha256=V6_PROOF,proof_updated_utc="2026-10-18T22:11:24+00:00",
                                             expires_at_utc="2026-10-19T02:08:51+00:00")
        and text.count('{"status": "BLOCKED", "code": "EXTERNAL_TIME_FORECAST_ACCEPTANCE", "source_admission": false}')==1
        and "No artifacts will be uploaded" in text,"EXTERNAL_REFUSAL_CONTROL")
    return refusal_value(c,auth["external_cohort"]["scope"])


def immutable_record(c,comment,tag):
    c.require(isinstance(comment,dict) and type(comment.get("id")) is int
        and comment.get("issue_url")==f"https://api.github.com/repos/{c.REPO}/issues/448"
        and comment.get("author_association")=="OWNER" and comment.get("user",{}).get("type")=="User"
        and type(comment["user"].get("id")) is int and comment["user"]["id"]>0
        and isinstance(comment.get("body"),str) and isinstance(comment.get("created_at"),str)
        and isinstance(comment.get("updated_at"),str) and comment["created_at"]==comment["updated_at"]
        and c.utc(c.CONTINUATION["first"])<=c.utc(comment["created_at"])<=c.utc()
        and c.utc(comment["created_at"])<c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48),
        "EXTERNAL_REFUSAL_OWNER")
    lines=[s[len(tag):] for s in comment["body"].splitlines() if s.startswith(tag)]
    c.require(len(lines)==1 and len(lines[0])<=4096,"EXTERNAL_REFUSAL_OWNER")
    value=c.decode(lines[0])
    proof=dict(reference=f"https://github.com/{c.REPO}/issues/448#issuecomment-{comment['id']}",
        comment_id=comment["id"],author_id=comment["user"]["id"],created_at=comment["created_at"],
        body_sha256=c.digest(comment["body"].encode()))
    return value,proof


def grant_record(c,source,pins,scope):
    c.require(isinstance(source,str) and c.re.fullmatch(r"[0-9a-f]{40}",source) and source!=V6_SOURCE
        and set(pins)==set(V6_PINS),"EXTERNAL_REFUSAL_SOURCE")
    return dict(schema="a1-sip-exact-no-meter-refusal-grant-v1",source_sha=source,
        code_pins_sha256=c.digest(c.encoded(pins)),old_auth_sha256=V6_AUTH,old_source_sha=V6_SOURCE,
        old_code_pins_sha256=c.digest(c.encoded(V6_PINS)),old_proof_sha256=V6_PROOF,
        refusal_evidence_sha256=c.digest(c.encoded(refusal_value(c,scope))),run_id=REFUSAL_RUN,
        log_sha256=REFUSAL_LOG,cohort_tail_sha256=COHORT23,family_tail_sha256=FAMILY50,
        actual_job_seconds=185,actual_dispatches=1,original_missing_meter_preserved=True,
        not_runtime_meter=True,no_price_result=True,unknown_storage_bytes_still_charged=302101,
        platform_costs="UNKNOWN_NOT_ZERO",limits=c.CONTINUED_LIMITS,active_limit_seconds=43200,
        dispatch_limit=40,expires_at_utc="2026-10-19T02:08:51+00:00")


def closure_payload(c,source,pins,scope,grant_comment):
    value,proof=immutable_record(c,grant_comment,"A1_SIP_NO_METER_REFUSAL_AUTHORIZATION ")
    c.require(value==grant_record(c,source,pins,scope),"EXTERNAL_REFUSAL_GRANT")
    return dict(schema="a1-sip-exact-no-meter-refusal-closed-v1",nonce=REFUSAL_NONCE,run_id=REFUSAL_RUN,
        capture_auth_sha256=V6_AUTH,scope=scope,refusal_evidence_sha256=value["refusal_evidence_sha256"],
        grant_reference=proof["reference"],grant_proof_sha256=c.digest(c.encoded(proof)),
        grant_created_at=proof["created_at"],grant_author_id=proof["author_id"],source_sha=source,
        code_pins_sha256=c.digest(c.encoded(pins)),actual_job_seconds=185,actual_dispatches=1,
        meter_observation="MISSING",not_runtime_meter=True,platform_costs="UNKNOWN_NOT_ZERO")


def closure_entry(c,payload,clock,family=False):
    c.require(isinstance(clock,str) and c.utc(payload["grant_created_at"])<=c.utc(clock)<=c.utc()
        and c.utc(clock)<c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48),"EXTERNAL_REFUSAL_CLOCK")
    return dict(sequence=51 if family else 24,kind="NO_METER_REFUSAL_CLOSED",
        auth_sha256=c.external_family_genesis() if family else V6_AUTH,
        previous_sha256=FAMILY50 if family else COHORT23,recorded_utc=clock,**payload)


def verify_closure_receipt(c,auth,receipt,grant_comment,seal_comment):
    sr=auth["external_cohort"]["source_revision"]
    sealed,seal_proof=immutable_record(c,seal_comment,"A1_SIP_NO_METER_REFUSAL_CLOSED ")
    c.require(type(sr["refusal_closure_comment_id"]) is int
        and seal_comment["id"]==sr["refusal_closure_comment_id"] and sealed==receipt
        and c.digest(c.encoded(receipt))==sr["refusal_closure_sha256"]
        and set(receipt)=={"schema","payload","cohort_event","family_event"}
        and receipt["schema"]=="a1-sip-exact-no-meter-refusal-receipt-v1","EXTERNAL_REFUSAL_RECEIPT")
    payload=closure_payload(c,auth["expected_master"],auth["code_pins"],auth["external_cohort"]["scope"],grant_comment)
    c.require(receipt["payload"]==payload and seal_proof["author_id"]==payload["grant_author_id"],
              "EXTERNAL_REFUSAL_RECEIPT")
    for field,family in (("cohort_event",False),("family_event",True)):
        item=receipt[field]
        c.require(set(item)=={"recorded_utc","sha256"},"EXTERNAL_REFUSAL_RECEIPT")
        event=closure_entry(c,payload,item["recorded_utc"],family)
        c.require(c.digest(c.encoded(event))==item["sha256"]
            and c.utc(item["recorded_utc"])<=c.utc(seal_proof["created_at"]),"EXTERNAL_REFUSAL_RECEIPT")
    c.require(c.utc(receipt["cohort_event"]["recorded_utc"])<=c.utc(receipt["family_event"]["recorded_utc"]),
              "EXTERNAL_REFUSAL_RECEIPT")
    return receipt


def verify_correction_state(c,state,used,active):
    c.require(state["examined"]==128 and state["parent"]==CP and used==USED and active==5123
        and state["receipts"][-1]==refusal_value(c,state["receipts"][-1]["cohort_scope"]),
        "EXTERNAL_CORRECTIVE_PARENT")


def correction_binding(c,auth,proof):
    return dict(schema="a1-sip-exact-refusal-source-correction-v1",prior_auth_sha256=V6_AUTH,
        prior_source_sha=V6_SOURCE,prior_proof_sha256=V6_PROOF,refusal_run_id=REFUSAL_RUN,
        refusal_closure_sha256=auth["external_cohort"]["source_revision"]["refusal_closure_sha256"],
        new_auth_sha256=c.validate_authorization(auth),new_source_sha=auth["expected_master"],
        new_code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),**proof)


def verify_correction_entry(c,entry,expected,closure,family=False):
    prior=closure["family_event" if family else "cohort_event"]["sha256"]
    c.require(set(entry)=={"sequence","kind","auth_sha256","previous_sha256","recorded_utc"}|set(expected)
        and entry["sequence"]==(52 if family else 25) and entry["kind"]=="REFUSAL_SOURCE_BOUND"
        and entry["auth_sha256"]==(c.external_family_genesis() if family else expected["new_auth_sha256"])
        and entry["previous_sha256"]==prior and all(entry[k]==v for k,v in expected.items())
        and isinstance(entry["recorded_utc"],str)
        and c.utc(expected["proof_updated_utc"])<=c.utc(entry["recorded_utc"])<=c.utc()
        and c.utc(entry["recorded_utc"])<c.utc(expected["expires_at_utc"]),"EXTERNAL_CORRECTIVE_BINDING")

MODULE = "tools/alpaca_sip_source_revision.py"
OLD_SOURCE = "18571d9ab03b45abd33fe76edfbb03744e7eb917"
OLD_AUTH = "cb2b3b73f2a0edd08a6ff40942d537ca21f5c125bc8ef2cb57e907ad8079dd81"
OLD_PROOF = "5c87d7e00ca1f4559ecffafeb07c6411fde7652f8b91afbb5e0c2297f8f23967"
OLD_REFERENCE = "https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-6251201164"
OLD_PINS = {
 ".github/workflows/alpaca_sip_private_backfill_v1.yml":"ef76f00eea26b6a65d2fd4722d07042824ddc7267b3d62f157882771fbe68c44",
 "tools/alpaca_sip_campaign.py":"d2d7b131ee5b25cbd6e4d6574c1bf6991311e210b95e04b2d6ed2e248e2ea649",
 "tools/alpaca_sip_private_backfill_v1.py":"01e94b59f4a587cf54b5bf5b6b25740c7eae8da12358817323d890a379180ec1",
 "tools/twelve_private_capture.py":"2cfe64847cb6a9d4777247968832dbdf5737eafc1ed5f47a2e7b6877bc27bdac",
 "tools/configure_macro_research_drive.py":"51c6210ae63f4e7522d5d73d8eb90c5c03348736a9638461772d116fcf51d2fc",
 "tools/macro_history_sources.py":"029ae7337618211c1520adc78c9199831ed739918070c6b29204e9110aa9ab08"}
CP = "f618ba19ebe83b44f8d74b889d18edc0493e69f1b551e565d908a3a913a2668f"
RECEIPT = "bb54b20662d51cc29ac7a715cecf9caaa0fa0ed5fbeacdcdf71572f4eae941f2"
COHORT_TAIL = "041485bcd4f1de9a07f8a58160a3a089209fe4f394c659dcb0b9bd01d2763c34"
FAMILY_TAIL = "a5846bbbc94524584c18982b0ccf2d8b74db5e97f102cd72a0d789b2f0f7de86"
NATIVE = "ac54ca283aa0577b99a08a774e1b743f3be693b486510fd9de3e5b3d93b853a4"
REQUEST = "bba8f690d5395eecd8a3fa946c7b405e00b14dd1f3ca4d4883ca4aedb558cdbb"
USED = dict(provider_gets=628,drive_requests=6167,drive_bytes=998980231,storage_bytes=90610661)
PROJECTED = dict(provider_gets=729,drive_requests=9443,drive_bytes=5730857188,storage_bytes=87682032)
SAMPLES = [
 "830138122f2b591b93101c71571f9284d03ceec3f57ce75b7025615472cf4028",
 "e974366106cfec7daf0630f3eab62bfbf3e623a35391570b81758703f578ff32",
 "231d256890c209ef5dace024a25cfafc5d6a8714abded3a8cca76f2752818814",
 "169676334e24fd05d807e921c1c358f39464764bfa0a9500d656717db8541156",
 "6bb92814144b4101b1429d745a5fc423268b84fb57eef3da9ef4597f5288fd0d",
 RECEIPT]
SPEC = dict(kind="SOURCE_REVISION",prior_auth=OLD_AUTH,examined=128,events=20,
            checkpoint_sha256=CP,receipt_sha256=RECEIPT,run_id=39138746776)
POLICY = dict(schema="a1-sip-cp128-time-forecast-acceptance-v1",
    human_request_sha256=REQUEST,prior_auth_sha256=OLD_AUTH,checkpoint_sha256=CP,
    original_active_seconds=4938,original_remaining_active_seconds=38262,
    maximum_time_forecast_seconds=38748,original_deficit_seconds=486,
    time_forecast_only=True,actual_hard_caps_unchanged=True,expiry_unchanged=True,
    no_new_native_or_old_post_retry=True,unknown_storage_bytes_still_charged=302101)


def policy_hash(c):
    return c.digest(c.encoded(POLICY))


def previous(c, auth):
    if control_corrective(auth):
        ex=dict(auth["external_cohort"],source_revision=dict(validity_reference=V8_VALIDITY_REFERENCE),
                proof_reference=V8_REFERENCE)
        return dict(auth,schema="r1000-sip-external-cohort-authorization-v8",expected_master=V8_SOURCE,
                    code_pins=dict(V8_PINS),account_permission_reference=V8_REFERENCE,external_cohort=ex)
    if renewed(auth):
        ex=dict(auth["external_cohort"])
        ex["source_revision"]=dict(policy_sha256=policy_hash(c),refusal_closure_sha256=V7_CLOSURE,
                                   refusal_closure_comment_id=V7_CLOSURE_COMMENT)
        ex["proof_reference"]=V7_REFERENCE
        return dict(auth,schema="r1000-sip-external-cohort-authorization-v7",expected_master=V7_SOURCE,
                    code_pins=dict(V7_PINS),account_permission_reference=V7_REFERENCE,external_cohort=ex)
    if corrective(auth):
        ex = dict(auth["external_cohort"])
        ex["source_revision"] = dict(policy_sha256=policy_hash(c))
        ex["proof_reference"] = V6_REFERENCE
        return dict(auth,schema="r1000-sip-external-cohort-authorization-v6",expected_master=V6_SOURCE,
                    code_pins=dict(V6_PINS),account_permission_reference=V6_REFERENCE,external_cohort=ex)
    ex = dict(auth["external_cohort"])
    ex.pop("source_revision")
    ex["proof_reference"] = OLD_REFERENCE
    return dict(auth,schema="r1000-sip-external-cohort-authorization-v5",
                expected_master=OLD_SOURCE,code_pins=dict(OLD_PINS),
                account_permission_reference=OLD_REFERENCE,external_cohort=ex)


def validate(c, auth):
    ex = auth["external_cohort"]
    if control_corrective(auth):
        sr=ex.get("source_revision",{})
        pattern=r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+"
        c.require(set(sr)=={"control_refusal_reference","control_refusal_sha256"}
            and isinstance(sr["control_refusal_reference"],str) and c.re.fullmatch(pattern,sr["control_refusal_reference"])
            and isinstance(sr["control_refusal_sha256"],str) and c.re.fullmatch(r"[0-9a-f]{64}",sr["control_refusal_sha256"])
            and c.validate_authorization(previous(c,auth))==V8_AUTH and auth["expected_master"]!=V8_SOURCE
            and isinstance(ex["proof_reference"],str) and ex["proof_reference"]!=V8_REFERENCE
            and auth["account_permission_reference"]==ex["proof_reference"] and c.re.fullmatch(pattern,ex["proof_reference"])
            and len(c.encoded(auth))<=15000,"EXTERNAL_CONTROL_SOURCE_AUTHORIZATION")
        return
    if renewed(auth):
        sr=ex.get("source_revision",{})
        c.require(set(sr)=={"validity_reference"} and isinstance(sr["validity_reference"],str)
            and c.re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",sr["validity_reference"])
            and c.validate_authorization(previous(c,auth))==V7_AUTH
            and auth["expected_master"] not in (V7_SOURCE,V6_SOURCE)
            and ex["proof_reference"]!=V7_REFERENCE and auth["account_permission_reference"]==ex["proof_reference"]
            and isinstance(ex["proof_reference"],str)
            and c.re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",ex["proof_reference"])
            and len(c.encoded(auth))<=15000,"EXTERNAL_VALIDITY_AUTHORIZATION")
        return
    if corrective(auth):
        sr=ex.get("source_revision",{})
        c.require(set(sr)=={"policy_sha256","refusal_closure_sha256","refusal_closure_comment_id"}
            and sr["policy_sha256"]==policy_hash(c)
            and isinstance(sr["refusal_closure_sha256"],str) and c.re.fullmatch(r"[0-9a-f]{64}",sr["refusal_closure_sha256"])
            and type(sr["refusal_closure_comment_id"]) is int and sr["refusal_closure_comment_id"]>0
            and c.validate_authorization(previous(c,auth))==V6_AUTH
            and auth["expected_master"]!=V6_SOURCE and ex["proof_reference"]!=V6_REFERENCE
            and auth["account_permission_reference"]==ex["proof_reference"]
            and isinstance(ex["proof_reference"],str)
            and c.re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",ex["proof_reference"])
            and len(c.encoded(auth))<=15000,"EXTERNAL_CORRECTIVE_SOURCE")
        return
    c.require(ex.get("source_revision") == dict(policy_sha256=policy_hash(c))
              and c.validate_authorization(previous(c,auth)) == OLD_AUTH
              and auth["expected_master"] != OLD_SOURCE
              and ex["proof_reference"] != OLD_REFERENCE
              and auth["account_permission_reference"] == ex["proof_reference"]
              and isinstance(ex["proof_reference"],str)
              and c.re.fullmatch(r"https://github\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+",
                                ex["proof_reference"])
              and len(c.encoded(auth)) <= 15000, "EXTERNAL_SOURCE_REVISION")


def commitment(c, auth):
    c.validate_authorization(auth)
    ex = dict(auth["external_cohort"])
    self_locator = dict(schema="a1-sip-current-owner-self-locator-v1")
    ex["proof_reference"] = self_locator
    projected = dict(auth,external_cohort=ex,account_permission_reference=self_locator)
    return c.digest(c.encoded(dict(schema="a1-sip-source-revision-consent-commitment-v1",authorization=projected)))


def proof_record(c, auth):
    if control_corrective(auth):
        record=proof_record(c,previous(c,auth))
        record.update(schema="a1-sip-external-cohort-consent-v6",expected_master=auth["expected_master"],
            code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),authorization_commitment_sha256=commitment(c,auth),
            control_source=dict(prior_auth_sha256=V8_AUTH,prior_source_sha=V8_SOURCE,prior_owner_reference=V8_REFERENCE,
                prior_proof_sha256=V8_PROOF,closure_reference=auth["external_cohort"]["source_revision"]["control_refusal_reference"],
                closure_sha256=auth["external_cohort"]["source_revision"]["control_refusal_sha256"],
                validity_grant_is_ancestor=True,closed_run_id=CONTROL_RUN,original_failure_cause="UNKNOWN",
                actual_control_seconds=195,actual_control_dispatches=1,prior_active_seconds=5318,prior_dispatches=23))
        return record
    if renewed(auth):
        record=proof_record(c,previous(c,auth))
        record.pop("source_revision");record.pop("corrective_source")
        record.update(schema="a1-sip-external-cohort-consent-v5",expected_master=auth["expected_master"],
            code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),authorization_commitment_sha256=commitment(c,auth),
            expires_at_utc=c.utc(VALIDITY_END).isoformat(),not_before_utc=VALIDITY_START,
            validity=dict(authority_sha256=VALIDITY_AUTHORITY,prior_auth_sha256=V7_AUTH,prior_proof_sha256=V7_PROOF,
                grant_reference=auth["external_cohort"]["source_revision"]["validity_reference"],
                grant_record_sha256=c.digest(c.encoded(validity_record(c,auth["expected_master"],auth["code_pins"],auth["external_cohort"]["scope"]))),
                original_expiry_utc=(c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48)).isoformat(),
                time_forecast_policy_sha256=policy_hash(c),refusal_closure_sha256=V7_CLOSURE,
                retained_native_settlement_sha256=NATIVE,prospective_only=True))
        return record
    if corrective(auth):
        record=proof_record(c,previous(c,auth))
        record.update(schema="a1-sip-external-cohort-consent-v4",expected_master=auth["expected_master"],
            code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),authorization_commitment_sha256=commitment(c,auth),
            corrective_source=dict(prior_auth_sha256=V6_AUTH,prior_source=V6_SOURCE,
                prior_owner_reference=V6_REFERENCE,prior_proof_sha256=V6_PROOF,
                refusal_run_id=REFUSAL_RUN,refusal_closure_sha256=auth["external_cohort"]["source_revision"]["refusal_closure_sha256"],
                refusal_closure_comment_id=auth["external_cohort"]["source_revision"]["refusal_closure_comment_id"],
                actual_refusal_seconds=185,actual_refusal_dispatches=1))
        return record
    record = external_proof_record(c,previous(c,auth))
    # Old native terms are independently verified through the retained v5 proof;
    # the current record grants a source revision, never a second native recovery.
    record.pop("native18_recovery")
    record.update(schema="a1-sip-external-cohort-consent-v3",expected_master=auth["expected_master"],
        code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),
        authorization_commitment_sha256=commitment(c,auth),
        source_revision=dict(policy=POLICY,prior_owner_reference=OLD_REFERENCE,prior_proof_sha256=OLD_PROOF,
            receipt_sha256=RECEIPT,cohort_tail_sha256=COHORT_TAIL,family_tail_sha256=FAMILY_TAIL,
            retained_native_settlement_sha256=NATIVE,source_change_only=True,additional_link_cost="UNKNOWN_NOT_ZERO"))
    return record


def binding(c, auth, proof):
    return dict(schema="a1-sip-cp128-source-revision-bound-v1",
        prior_auth_sha256=OLD_AUTH,checkpoint_sha256=CP,receipt_sha256=RECEIPT,
        cohort_tail_sha256=COHORT_TAIL,family_tail_sha256=FAMILY_TAIL,
        native_settlement_sha256=NATIVE,policy_sha256=policy_hash(c),
        new_auth_sha256=c.validate_authorization(auth),new_source_sha=auth["expected_master"],
        new_code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),**proof)


def verify_entry(c, entry, expected, family=False):
    common = {"sequence","kind","auth_sha256","previous_sha256","recorded_utc"}
    c.require(isinstance(entry,dict) and set(entry) == common|set(expected)
        and entry["kind"] == "SOURCE_REVISION_BOUND"
        and type(entry["sequence"]) is int and entry["sequence"] == (48 if family else 21)
        and entry["auth_sha256"] == (c.external_family_genesis() if family else expected["new_auth_sha256"])
        and entry["previous_sha256"] == (FAMILY_TAIL if family else COHORT_TAIL)
        and all(entry.get(k) == v for k,v in expected.items())
        and c.utc(expected["proof_updated_utc"]) <= c.utc(entry["recorded_utc"])
            < c.utc(expected["expires_at_utc"]) and c.utc(entry["recorded_utc"]) <= c.utc(),
        "EXTERNAL_SOURCE_REVISION_BINDING")


def time_acceptance(c, auth, observed, forecast, *, canonical_run=None):
    c.require(c.has_source_revision(auth),"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    validate(c,auth)
    clock=c.utc()
    if canonical_run is not None:
        c.require(renewed(auth),"EXTERNAL_VALIDITY_RUN_CLOCK")
        verify_validity_run(c,auth,canonical_run,observed["epoch_proofs"][c.validate_authorization(auth)])
        clock=c.utc(canonical_run["created_at"])
    basis=calibration_basis(c,auth,observed)
    c.require(observed["examined"] == 128 and observed["parent_sha"] == CP
        and observed["used"] == USED and basis["active_seconds"] == 4938
        and len(basis["runs"]) == 21
        and [c.digest(c.encoded(r)) for r in basis["cohort_receipts"]] == SAMPLES
        and basis["cohort_durations"] == [274,305,275,255,380,372]
        and forecast["projected"] == PROJECTED and forecast["fits"] is False
        and type(forecast["active_seconds"]) is int and 0 < forecast["active_seconds"] <= 38748
        and forecast["dispatches"] == 10 and forecast["batch_sizes"] == [32]*9+[1]
        and forecast["margin"] == 1.25 and forecast["price_samples"] == 5
        and forecast["one_time_recovery_samples"] == 1 and forecast["price_processed"] == 124
        and all(forecast["projected"][k] <= observed["remaining"][k] for k in c.LIMITS)
        and len(observed["runs"])+forecast["dispatches"]-(observed.get("current_run") is not None) <= 40
        and observed["active_seconds"]+7800 <= c.active_limit(auth)
        and (not renewed(auth) or c.utc(VALIDITY_START)<=clock) and clock<expiry(c,auth),
        "EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    result=dict(schema=POLICY["schema"],policy_sha256=policy_hash(c),checkpoint_sha256=CP,
                original_forecast_seconds=38748,accepted_forecast_seconds=forecast["active_seconds"],
                original_remaining_seconds=38262,forecast_fits=False,actual_limits_unchanged=True)
    if corrective(auth):
        result.update(live_active_seconds=5123,live_prior_dispatches=22,
            refusal_closure_sha256=corrective_auth(c,auth)["external_cohort"]["source_revision"]["refusal_closure_sha256"])
    if renewed(auth):
        result.update(validity_authority_sha256=VALIDITY_AUTHORITY,validity_not_before_utc=VALIDITY_START,
                      validity_expires_at_utc=VALIDITY_END)
    if control_corrective(auth):
        result.update(live_active_seconds=5318,live_prior_dispatches=23,
            control_refusal_closure_sha256=auth["external_cohort"]["source_revision"]["control_refusal_sha256"])
    return result


def verify_transition(c, state, used, active):
    c.require(state["examined"] == 128 and state["parent"] == CP
        and state["receipts"] and c.digest(c.encoded(state["receipts"][-1])) == RECEIPT
        and used == USED and active == 4938,"EXTERNAL_SOURCE_REVISION_PARENT")


def verify_marker(c, auth, value, observed, run=None):
    c.require(value.get("source_revision_policy_sha256") == policy_hash(c),"EXTERNAL_SOURCE_REVISION_RECEIPT")
    if value["examined_before"] == 128:
        if renewed(auth):
            c.require(isinstance(run,dict) and type(run.get("id")) is int and run["id"]==value.get("run_id")
                and run.get("head_sha")==auth["expected_master"] and run.get("run_attempt")==1,
                "EXTERNAL_VALIDITY_RUN_CLOCK")
        expected = time_acceptance(c,auth,observed,c.external_forecast(auth,observed),
                                   canonical_run=run if renewed(auth) else None)
        c.require(value.get("time_forecast_exception") == expected,"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    else:
        c.require("time_forecast_exception" not in value,"EXTERNAL_TIME_FORECAST_ACCEPTANCE")


def external_proof_record(c, auth):
    if c.has_source_revision(auth):
        return proof_record(c,auth)
    ex = auth["external_cohort"]
    result = dict(schema="a1-sip-external-cohort-consent-v1", budget_task_key=c.TASK,
                scope=ex["scope"], auth_sha256=c.validate_authorization(auth),
                prior_auth_sha256=c.CONTINUATION["auth"],
                prior_epoch_auth_sha256=[c.validate_authorization(a) for a in ex["prior_epochs"]],
                intake_manifest_sha256=ex["intake_manifest_sha256"], receipt_dedupe_sha256=ex["receipt_dedupe_sha256"],
                initial_checkpoint_sha256=c.external_genesis(ex["scope"]),
                original_checkpoint_sha256=c.CONTINUATION["checkpoint"],
                original_journal_event_sha256=c.CONTINUATION["event"], original_usage=c.CONTINUATION["used"],
                first_canonical_utc=c.CONTINUATION["first"],
                expires_at_utc=(c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48)).isoformat(),
                limits=c.CONTINUED_LIMITS, active_seconds_limit=43200, dispatch_limit=40,
                expected_master=auth["expected_master"], code_pins_sha256=c.digest(c.encoded(auth["code_pins"])),
                bindings=c.CONTINUATION["bindings"], personal_historical_capture_requested=True,
                private_noncommercial=True, supplier_rights_verified=False, account_rotation=False,
                original_seed_unchanged=True, budget_reset=False)
    if "named_recovery" in ex:
        result.update(named_recovery=dict(prior_capture_auth_sha256=c.NAMED_RECOVERY["prior_auth"],
            failed_run_id=c.NAMED_RECOVERY["run_id"], failed_receipt_sha256=c.NAMED_RECOVERY["receipt_sha256"],
            checkpoint_sha256=c.NAMED_RECOVERY["checkpoint_sha256"], examined=c.NAMED_RECOVERY["examined"],
            recovery_dispatch_limit=1, first_recovery_batch_limit=8,
            unknown_http_status_acknowledged=True, request_sha256=c.NAMED_RECOVERY["request_sha256"]))
    if "drive_recovery" in ex:
        result.update(drive_recovery=dict(prior_capture_auth_sha256=c.DRIVE_RECOVERY["prior_auth"],
            failed_run_id=c.DRIVE_RECOVERY["run_id"], failed_receipt_sha256=c.DRIVE_RECOVERY["receipt_sha256"],
            checkpoint_sha256=c.DRIVE_RECOVERY["checkpoint_sha256"], examined=c.DRIVE_RECOVERY["examined"],
            recovery_dispatch_limit=1, first_recovery_batch_limit=9,
            uncertain_create_outcome_acknowledged=True, request_sha256=c.DRIVE_RECOVERY["request_sha256"]))
    if "materialization_recovery" in ex:
        spec = c.MATERIALIZATION_RECOVERY
        result.update(materialization_recovery=dict(prior_capture_auth_sha256=spec["prior_auth"],
            failed_run_id=spec["run_id"], failed_receipt_sha256=spec["receipt_sha256"],
            checkpoint_sha256=spec["checkpoint_sha256"], examined=spec["examined"],
            recovery_dispatch_limit=1, first_recovery_batch_limit=9,
            normalized_only_derivation=True, original_create_outcome_unknown=True,
            request_sha256=spec["request_sha256"]))
    if "native18_recovery" in ex:
        # A GitHub comment ID exists only after POST. Bind the complete terms
        # before that single create, then bind the returned real URL at runtime.
        result.pop("auth_sha256")
        result.update(schema="a1-sip-external-cohort-consent-v2",
                      authorization_commitment_sha256=c.native18_consent_commitment(auth))
        result["native18_recovery"] = dict(
            failed_run_id=c.NATIVE18_RECOVERY["run_id"],
            failed_meter_sha256=c.NATIVE18_RECOVERY["receipt_sha256"],
            native_run_id=c.NATIVE18_RUN, native_meter_sha256=c.NATIVE18_METER,
            native_source_sha=c.NATIVE18_MASTER, checkpoint_sha256=c.NATIVE18_RECOVERY["checkpoint_sha256"],
            policy="HOLD_EXACT4_UNCERTAIN_STORAGE", symbols=["VLO","MFG","BP","BTI"],
            unknown_storage_bytes_still_charged=302101, absence_proven=False,
            failed_request_body_hash_known=False, old_post_retry_authorized=False,
            native_usage=c.NATIVE18_USAGE, native_job_seconds=162, native_reserved_seconds=900,
            native_dispatches=1, first_recovery_batch_limit=4, recovery_dispatch_limit=1,
            past_diagnostics_status="UNKNOWN_NOT_ZERO", total_platform_cost_verified=False,
            settlement_sha256=ex["native18_recovery"]["settlement_sha256"])
    return result


def external_forecast_samples(c, auth, observed):
    """Consume the same validated history; a typed one-time hold is not price work."""
    from tools import alpaca_sip_private_backfill_v1 as cap
    c.validate_authorization(auth)
    versions = {c.validate_authorization(a):a for a in c.external_variants(auth)}
    receipts, durations = price_observations(c,auth,observed)
    c.require(len(receipts) == len(durations) and 0 < len(receipts) <= 40, "EXTERNAL_FORECAST_SAMPLE")
    price, one_time, prefix = [], [], 0
    for r, seconds in zip(receipts, durations):
        a = versions.get(r.get("auth_sha256"))
        proof = observed["epoch_proofs"].get(r.get("auth_sha256"))
        c.require(a is not None and isinstance(proof,dict)
                and isinstance(proof.get("proof_sha256"),str) and c.re.fullmatch(r"[0-9a-f]{64}",proof["proof_sha256"])
                and r.get("schema") == "a1-sip-campaign-meter-v1" and r.get("task_key") == c.TASK
                and r.get("source_sha") == a["expected_master"]
                and r.get("cohort_scope") == auth["external_cohort"]["scope"]
                and r.get("external_proof_sha256") == proof.get("proof_sha256")
                and r.get("finalized") is True and r.get("preflight_only") is False
                and r.get("status") in ("COMPLETE","BLOCKED")
                and type(r.get("run_id")) is int and r["run_id"] > 0
                and type(r.get("examined_before")) is int and r["examined_before"] == prefix,
                "EXTERNAL_FORECAST_SCOPE")
        after = r.get("examined_after")
        c.require(type(after) is int and after > prefix and after <= observed["examined"]
                and isinstance(seconds,(int,float)) and not isinstance(seconds,bool)
                and c.math.isfinite(seconds) and seconds > 0, "EXTERNAL_FORECAST_SAMPLE")
        usage, states = r.get("usage"), r.get("new_states")
        c.require(isinstance(usage,dict) and set(usage) == set(c.LIMITS)
                and all(type(v) is int and v >= 0 for v in usage.values())
                and isinstance(states,dict) and set(states) == {"VALID_COLLECTED","VERIFIED_NO_DATA","QUARANTINED"}
                and all(type(v) is int and v >= 0 for v in states.values())
                and sum(states.values()) == after-prefix, "EXTERNAL_FORECAST_SAMPLE")
        native = a["external_cohort"].get("native18_recovery")
        if native is not None:
            c.require(r.get("native18_settlement_sha256") == native["settlement_sha256"], "EXTERNAL_FORECAST_TYPE")
        if "uncertain_storage_hold" in r or native is not None and prefix == 76:
            hold = r.get("uncertain_storage_hold")
            c.require(native is not None and prefix == 76 and after == 80 and not one_time
                    and r["status"] == "COMPLETE" and r.get("rows_verified") == 0
                    and states == dict(VALID_COLLECTED=0,VERIFIED_NO_DATA=0,QUARANTINED=4)
                    and usage["provider_gets"] == 0 and r.get("recovery_run") == c.NATIVE18_RECOVERY["run_id"]
                    and isinstance(hold,dict) and set(hold) == {"evidence","marker_sha256","checkpoint_sha256"},
                    "EXTERNAL_FORECAST_TYPE")
            cap.verify_storage_quarantine(hold["evidence"],r["cohort_scope"])
            evidence = hold["evidence"]
            c.require(evidence.get("authorization_sha256") == r["auth_sha256"]
                    and evidence.get("external_proof_sha256") == proof["proof_sha256"]
                    and evidence.get("native_settlement_sha256") == native["settlement_sha256"]
                    and evidence.get("recovery_run_id") == r["run_id"]
                    and isinstance(hold["marker_sha256"],str) and c.re.fullmatch(r"[0-9a-f]{64}",hold["marker_sha256"])
                    and hold["checkpoint_sha256"] == r["checkpoint_sha256"], "EXTERNAL_FORECAST_TYPE")
            one_time.append((r,seconds))
        else:
            price.append((r,seconds))
        prefix = after
    c.require(prefix == observed["examined"] and len(price) >= 2, "EXTERNAL_FORECAST_SAMPLE")
    return price, one_time


def external_price_envelope(c, captures, values, jobs):
    """The same nonnegative growth envelope, rounded only after exact arithmetic."""
    normalized = [c.Fraction(str(v))*32/(r["examined_after"]-r["examined_before"])
                  for r,v in zip(captures,values)]
    slope = max([c.Fraction(0)] + [max(0,b-a)*32/(right["examined_before"]-left["examined_before"])
                for a,b,left,right in zip(normalized,normalized[1:],captures,captures[1:])])
    return jobs*max(normalized) + slope*jobs*(jobs+1)/2


def external_forecast(c, auth, observed):
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    if not observed["examined"] or observed["examined"] % 128:
        return None
    price, one_time = c.external_forecast_samples(auth,observed)
    count = len(external_cohort(auth["external_cohort"]["input_csv"].encode()))
    prefix, schedule = observed["examined"], []
    while prefix < count:
        size = c.external_batch(prefix,count,auth)
        schedule.append((prefix,size)); prefix += size
    c.require(schedule, "EXTERNAL_FORECAST_SAMPLE")
    c.require(observed["remaining"] == {k:c.CONTINUED_LIMITS[k]-observed["used"][k] for k in c.LIMITS},
            "EXTERNAL_FORECAST_BUDGET")
    captures = [r for r,_ in price]
    processed = sum(r["examined_after"]-r["examined_before"] for r in captures)
    jobs, remaining = len(schedule), count-observed["examined"]
    projected = {}
    for key in c.LIMITS:
        values = [r["usage"][key] for r in captures]
        if key in ("provider_gets","storage_bytes"):
            estimate = c.Fraction(sum(values)*remaining,processed)
        elif key == "drive_requests":
            overhead = max([4]+[r["usage"][key]-8*c.math.ceil(r["examined_before"]/4)
                         -28*c.math.ceil((r["examined_after"]-r["examined_before"])/4) for r in captures])
            estimate = sum(8*c.math.ceil(start/4)+28*c.math.ceil(size/4)+overhead for start,size in schedule)
        else:
            estimate = c.external_price_envelope(captures,values,jobs)
        projected[key] = c.math.ceil(estimate*c.Fraction(5,4))
    seconds = c.math.ceil(c.external_price_envelope(captures,[s for _,s in price],jobs)*c.Fraction(5,4))
    return dict(projected=projected, active_seconds=seconds, dispatches=jobs, estimate_only=True,
        price_samples=len(price), one_time_recovery_samples=len(one_time), price_processed=processed,
        cohort_count=count,remaining_candidates=remaining,batch_sizes=[size for _,size in schedule],margin=1.25,
        fits=all(projected[k] <= observed["remaining"][k] for k in c.LIMITS)
             and seconds <= c.active_limit(auth)-observed["active_seconds"]
             and len(observed["runs"])+jobs <= 40)



def native18_consent_commitment(c, auth):
    """Detached v5 consent only; never replaces the full runtime auth SHA."""
    c.require(auth.get('schema') == 'r1000-sip-external-cohort-authorization-v5' and isinstance(auth.get('external_cohort'), dict) and ('native18_recovery' in auth['external_cohort']), 'EXTERNAL_NATIVE18_RECOVERY')
    projected = dict(auth, external_cohort=dict(auth['external_cohort']))
    self_locator = dict(schema='a1-sip-current-owner-self-locator-v1')
    projected['account_permission_reference'] = self_locator
    projected['external_cohort']['proof_reference'] = self_locator
    return c.digest(c.encoded(dict(schema='a1-sip-native18-consent-commitment-v1', authorization=projected)))

def validate_native18_evidence(c, run, value, jobs):
    """Validate the exact completed diagnostic, never a capture-shaped substitute."""
    c.require(isinstance(value, dict) and c.digest(c.encoded(value)) == c.NATIVE18_METER and (value.get('schema') == 'a1-native-drive-read-meter-v1') and (value.get('run_id') == c.NATIVE18_RUN) and (type(value.get('run_id')) is int) and (value.get('run_attempt') == 1) and (value.get('source_sha') == c.NATIVE18_MASTER) and (value.get('finalized') is True) and (value.get('status') == 'COMPLETE') and (value.get('usage') == c.NATIVE18_USAGE) and all((type(v) is int for v in value['usage'].values())) and (value.get('observed_google_body_bytes') == 4726) and (value.get('transfer_definition') == c.METRIC) and (value.get('active_seconds_reservation') == 900) and (value.get('dispatch_reservation') == 1) and (value.get('failed_run_id') == c.NATIVE18_RECOVERY['run_id']) and (value.get('failed_meter_sha256') == c.NATIVE18_RECOVERY['receipt_sha256']) and (value.get('parent_checkpoint_sha256') == c.NATIVE18_RECOVERY['checkpoint_sha256']) and (value.get('examined_before') == 76) and (value.get('pending_external_read_proof_sha256') == 'e25fca3a43a14d8d44b6615a758cce55fd8c665dbafd6bf653b639a6d3400b1d') and (value.get('result') == dict(positive_control_verified=True, files_count=1, candidate_count=0, owner_sha256=c.CONTINUATION['bindings']['owner_sha256'], absence_proven=False, failed_request_body_hash_known=False)) and all((value.get(k) is False for k in ('capture_allowed', 'source_admission', 'pit_verified', 'economic_authority'))) and (value.get('subsequent_capture_requires_separate_native_meter_settlement') is True), 'EXTERNAL_NATIVE18_METER')
    pending = value.get('pending_external_read_accounting')
    c.require(isinstance(pending, dict) and pending.get('basis') == c.NATIVE_READ_SCOPE_BASIS and (pending.get('status') == 'UNKNOWN_NOT_ZERO') and (pending.get('usage') == dict(provider_gets=0, storage_bytes=0, drive_requests=None, drive_bytes=None)), 'EXTERNAL_NATIVE18_UNKNOWN')
    c.require(run.get('id') == c.NATIVE18_RUN and type(run.get('id')) is int and (run.get('run_attempt') == 1) and (type(run.get('run_attempt')) is int) and (run.get('status') == 'completed') and (run.get('conclusion') == 'success') and (run.get('head_sha') == c.NATIVE18_MASTER) and (run.get('head_branch') == 'master') and (run.get('event') == 'workflow_dispatch') and (run.get('display_title') == 'a1-sip ' + value['nonce'] + ' native-read39085031884') and (run.get('created_at') == '2026-10-18T06:23:17Z'), 'EXTERNAL_NATIVE18_RUN')
    expected = [(117605461102, 'offline', '2026-10-18T06:23:23Z', '2026-10-18T06:24:47Z'), (117605710106, 'reconcile', '2026-10-18T06:24:50Z', '2026-10-18T06:26:08Z')]
    c.require(isinstance(jobs, dict) and jobs.get('total_count') == 2 and isinstance(jobs.get('jobs'), list) and (len(jobs['jobs']) == 2), 'EXTERNAL_NATIVE18_JOBS')
    actual = sorted(jobs['jobs'], key=lambda j: j.get('id', 0))
    c.require([(j.get('id'), j.get('name'), j.get('started_at'), j.get('completed_at')) for j in actual] == expected and all((j.get('status') == 'completed' and j.get('conclusion') == 'success' for j in actual)), 'EXTERNAL_NATIVE18_JOBS')
    seconds = sum(((c.utc(j['completed_at']) - c.utc(j['started_at'])).total_seconds() for j in actual))
    c.require(seconds == 162 and seconds <= value['active_seconds_reservation'], 'EXTERNAL_NATIVE18_JOBS')
    return dict(meter_sha256=c.NATIVE18_METER, run_id=c.NATIVE18_RUN, source_sha=c.NATIVE18_MASTER, usage=dict(c.NATIVE18_USAGE), active_seconds=162, dispatches=1, reserved_active_seconds=900, checkpoint_sha256=c.NATIVE18_RECOVERY['checkpoint_sha256'], pending_external_read_proof_sha256=value['pending_external_read_proof_sha256'])

def native18_event_payload(c, source_sha, code_pins):
    c.require(isinstance(source_sha, str) and c.re.fullmatch('[0-9a-f]{40}', source_sha) and (source_sha not in (c.NATIVE18_MASTER, c.NATIVE18_PRIOR_SOURCE['expected_master'])) and isinstance(code_pins, dict) and (set(code_pins) == set(c.PINS)) and all((isinstance(h, str) and c.re.fullmatch('[0-9a-f]{64}', h) for h in code_pins.values())), 'EXTERNAL_NATIVE18_SOURCE')
    from tools.alpaca_sip_private_backfill_v1 import STORAGE_QUARANTINE
    scope = dict(task_key='R1000-DISCOVERY-EXPANSION-INTAKE-20261017', namespace='top500-20261017', input_sha256=STORAGE_QUARANTINE['input_sha256'])
    return dict(schema='a1-native18-shared-settlement-v1', capture_auth_sha256=c.NATIVE18_RECOVERY['prior_auth'], scope=scope, run_id=c.NATIVE18_RUN, source_sha=c.NATIVE18_MASTER, meter_sha256=c.NATIVE18_METER, usage=dict(c.NATIVE18_USAGE), active_seconds=162, reserved_active_seconds=900, dispatches=1, checkpoint_sha256=c.NATIVE18_RECOVERY['checkpoint_sha256'], pending_external_read_proof_sha256='e25fca3a43a14d8d44b6615a758cce55fd8c665dbafd6bf653b639a6d3400b1d', unknown_storage_bytes_still_charged=302101, absence_proven=False, failed_request_body_hash_known=False, total_platform_cost_verified=False, settled_by_source_sha=source_sha, settled_by_code_pins_sha256=c.digest(c.encoded(code_pins)))


def external_progress(c, auth, observed, status):
    from tools.alpaca_sip_private_backfill_v1 import external_cohort
    receipts = [r for r in observed['cohort_receipts'] if not (c.has_source_revision(auth) and c._revision_module().is_refusal(r))]
    result=dict(task_key=auth['external_cohort']['scope']['task_key'], budget_task_key=c.TASK, status=status, cohort_scope=auth['external_cohort']['scope'], examined=observed['examined'], cohort_count=len(external_cohort(auth['external_cohort']['input_csv'].encode())), states={k: sum((r['new_states'][k] for r in receipts)) for k in ('VALID_COLLECTED', 'VERIFIED_NO_DATA', 'QUARANTINED')}, rows_verified=sum((r['rows_verified'] for r in receipts)), charged_usage=observed['used'], remaining=observed['remaining'], active_seconds=observed['active_seconds'], workflow_dispatches=len(observed['runs']), checkpoint_sha256=observed['parent_sha'], first_canonical_utc=observed['first'].isoformat(), source_admission=False, pit_verified=False, economic_authority=False)
    if renewed(auth):result.update(validity_not_before_utc=VALIDITY_START,validity_expires_at_utc=VALIDITY_END)
    return result


def verify_external_proof(c, auth, expected, comment, grant=None, control_link=None):
    """Execution consent for THIS input, explicitly no fabricated supplier rights."""
    reference = auth['external_cohort']['proof_reference']
    comment_id = int(reference.rsplit('-', 1)[1])
    author = comment.get('user', {})
    c.require(comment.get('id') == comment_id and type(comment.get('id')) is int and (comment.get('issue_url') == f'https://api.github.com/repos/{c.REPO}/issues/448') and (comment.get('author_association') == 'OWNER') and (author.get('type') == 'User') and (type(author.get('id')) is int) and (author['id'] > 0) and isinstance(comment.get('body'), str), 'EXTERNAL_ATTESTOR')
    tag = 'A1_SIP_EXTERNAL_COHORT_CONSENT '
    lines = [line[len(tag):] for line in comment['body'].splitlines() if line.startswith(tag)]
    c.require(len(lines) == 1 and len(lines[0]) <= 4096, 'EXTERNAL_PROOF')
    record = c.decode(lines[0])
    c.require(isinstance(record, dict) and c.encoded(record) == c.encoded(expected), 'EXTERNAL_PROOF')
    if c.has_source_revision(auth):
        c.require(isinstance(comment.get('created_at'), str) and isinstance(comment.get('updated_at'), str) and (comment['created_at'] == comment['updated_at']), 'EXTERNAL_SOURCE_REVISION_PROOF')
    elif 'native18_recovery' in auth['external_cohort']:
        c.native18_consent_event(auth, comment)
    created, updated = (c.utc(comment.get('created_at')), c.utc(comment.get('updated_at')))
    c.require(c.utc(c.CONTINUATION['first']) <= created <= updated <= c.utc() and updated < c.utc(expected['expires_at_utc']), 'EXTERNAL_PROOF_CLOCK')
    if renewed(auth):
        ancestor=previous(c,auth) if control_corrective(auth) else auth
        grant_proof = verify_validity_grant(c, ancestor, grant)
        c.require(grant_proof['author_id'] == author['id'] and c.utc(grant_proof['created_at']) <= created and (c.utc(VALIDITY_START) <= created < c.utc(VALIDITY_END)), 'EXTERNAL_VALIDITY_PROOF')
        if control_corrective(auth):
            c.require(isinstance(control_link,dict) and control_link.get("prior_proof",{}).get("proof_sha256")==V8_PROOF
                and c.validate_authorization(ancestor)==V8_AUTH
                and control_link["seal_proof"]["author_id"]==author["id"]
                and c.utc(control_link["seal_proof"]["created_at"])<=created
                and c.digest(c.encoded(control_link["receipt"]))==auth["external_cohort"]["source_revision"]["control_refusal_sha256"],
                "EXTERNAL_CONTROL_SOURCE_PROOF")
    proof = dict(reference=reference, comment_id=comment_id, author_id=author['id'], created_at=created.isoformat(), updated_at=updated.isoformat(), body_sha256=c.digest(comment['body'].encode()), record=record)
    return dict(proof_sha256=c.digest(c.encoded(proof)), proof_updated_utc=updated.isoformat(), expires_at_utc=expected['expires_at_utc'])

def native18_consent_event(c, auth, comment):
    tag = 'A1_SIP_NATIVE18_SETTLEMENT '
    lines = [line[len(tag):] for line in comment['body'].splitlines() if line.startswith(tag)]
    c.require(len(lines) == 1 and len(lines[0]) <= 4096 and isinstance(comment.get('created_at'), str) and (comment['created_at'] == comment.get('updated_at')), 'EXTERNAL_NATIVE18_SETTLEMENT_PROOF')
    entry = c.decode(lines[0])
    c.verify_native18_event(entry, auth['expected_master'], auth['code_pins'], auth['external_cohort']['native18_recovery']['settlement_sha256'])
    c.require(c.utc(entry['recorded_utc']) <= c.utc(comment['created_at']), 'EXTERNAL_NATIVE18_SETTLEMENT_PROOF')
    return entry


def named_failed_receipt(c, run, value, auth):
    for spec in c.external_recoveries(auth):
        matched = run.get('id') == spec['run_id'] and run.get('run_attempt') == 1 and (run.get('conclusion') == 'failure') and (value.get('status') == 'BLOCKED') and (value.get('reason') == spec.get('reason', 'HTTP_ERROR')) and (value.get('auth_sha256') == spec['prior_auth']) and (c.digest(c.encoded(value)) == spec['receipt_sha256']) and (value.get('checkpoint_sha256') == spec['checkpoint_sha256']) and (value.get('examined_after') == spec['examined'])
        if matched and spec is c.NATIVE18_RECOVERY:
            c.require(value.get('last_transport_failure') == dict(http_status=502, method='POST', phase='HEADER_OPEN', request_category='DRIVE_CREATE', request_ordinal=265), 'EXTERNAL_NATIVE18_FAILURE_DIAGNOSTIC')
        if matched and spec is c.DRIVE_RECOVERY:
            c.require(value.get('last_transport_failure') == dict(http_status=502, method='POST', phase='HEADER_OPEN', request_category='DRIVE_CREATE', request_ordinal=343), 'EXTERNAL_DRIVE_FAILURE_DIAGNOSTIC')
        if matched:
            return True
    return False

def external_batch(c, examined, count, auth=None):
    c.integer(examined, count)
    if auth and 'native18_recovery' in auth['external_cohort'] and (examined == 76):
        c.require(count == 417, 'EXTERNAL_NATIVE18_RECOVERY')
        return 4
    c.require(examined < count <= 500, 'EXTERNAL_COHORT_COMPLETE')
    return min(32, count - examined, 128 - examined % 128)


def external_genesis(c, scope):
    from tools.alpaca_sip_private_backfill_v1 import external_scope
    return c.digest(c.encoded(dict(schema='a1-external-logical-genesis-v1', scope=external_scope(scope), start='2016-01-04', end='2026-10-14', feed='sip', adjustments=['raw', 'split'])))

def external_family_genesis(c):
    return c.digest(c.encoded(dict(schema='a1-external-budget-genesis-v1', task_key=c.TASK, prior_auth_sha256=c.CONTINUATION['auth'], prior_event_sha256=c.CONTINUATION['event'], first=c.CONTINUATION['first'], limits=c.CONTINUED_LIMITS, active_seconds_limit=43200, dispatch_limit=40)))


def verify_orphan_inventory(c, evidence):
    c.require(isinstance(evidence, dict) and set(evidence) == {'schema', 'observed_at_utc', 'window', 'files_count', 'has_more', 'entries'} and (evidence['schema'] == 'a1-bounded-orphan-inventory-v1') and (evidence['window'] == [c.DRIVE_RECOVERY['window_start'], c.DRIVE_RECOVERY['window_end']]) and (evidence['files_count'] is None or (type(evidence['files_count']) is int and 0 <= evidence['files_count'] <= 1000000)) and (type(evidence['has_more']) is bool) and isinstance(evidence['entries'], list) and (len(evidence['entries']) <= 8) and isinstance(evidence['observed_at_utc'], str) and (c.utc(c.DRIVE_RECOVERY['window_end']) <= c.utc(evidence['observed_at_utc']) <= c.utc()), 'EXTERNAL_ORPHAN_DIAGNOSTIC')
    for row in evidence['entries']:
        c.require(isinstance(row, dict) and set(row) == {'kind', 'sha256', 'bytes', 'created_at_utc'} and (row['kind'] in {'RAW', 'NORMALIZED', 'JSON', 'OTHER'}) and (row['sha256'] is None or (isinstance(row['sha256'], str) and c.re.fullmatch('[0-9a-f]{64}', row['sha256']))) and (row['bytes'] is None or (type(row['bytes']) is int and 0 <= row['bytes'] <= 16000000)) and (row['created_at_utc'] is None or c.utc(c.DRIVE_RECOVERY['window_start']) <= c.utc(row['created_at_utc']) <= c.utc()), 'EXTERNAL_ORPHAN_DIAGNOSTIC')


def verify_drive_reuse(c, reuse, identity):
    material = isinstance(reuse, dict) and 'materialization' in reuse
    spec = c.MATERIALIZATION_RECOVERY if material else c.DRIVE_RECOVERY
    c.require(isinstance(reuse, dict) and set(reuse) == {'failed_run_id', 'capture_source_sha', 'derivation_source_sha', 'raw_sha256', 'normalized_sha256', 'external_proof_sha256', 'derivation_run_id', 'derivation_auth_sha256', 'parent_checkpoint_sha256', 'derived_at_utc', 'failed_run_observation_window'} | ({'materialization'} if material else set()) and (reuse['failed_run_id'] == spec['run_id']) and (type(reuse['failed_run_id']) is int) and (reuse['capture_source_sha'] == c.DRIVE_RECOVERY['master']) and (reuse['derivation_source_sha'] == identity['source_sha']) and (type(reuse['derivation_run_id']) is int) and (reuse['derivation_run_id'] == identity['run_id']) and (reuse['derivation_auth_sha256'] == identity['auth_sha256']) and (reuse['external_proof_sha256'] == identity['external_proof_sha256']) and (reuse['parent_checkpoint_sha256'] == c.DRIVE_RECOVERY['checkpoint_sha256']) and (reuse['failed_run_observation_window'] == [c.DRIVE_RECOVERY['window_start'], c.DRIVE_RECOVERY['window_end']]) and all((isinstance(reuse[k], str) and c.re.fullmatch('[0-9a-f]{64}', reuse[k]) for k in ('raw_sha256', 'normalized_sha256'))) and isinstance(reuse['derived_at_utc'], str) and (c.utc(c.DRIVE_RECOVERY['window_end']) <= c.utc(reuse['derived_at_utc']) <= c.utc()), 'EXTERNAL_ORPHAN_PROVENANCE')
    if material:
        data = reuse['materialization']
        evidence = identity.get('orphan_inventory')
        c.verify_orphan_inventory(evidence)
        entries = evidence['entries']
        originals = [row for row in entries if row['kind'] == 'RAW']
        normalized = [row for row in entries if row['kind'] == 'NORMALIZED']
        c.require(evidence['has_more'] is False and evidence['files_count'] == len(entries) and (1 <= len(entries) <= 8) and (len(originals) == 1) and (len(normalized) <= 1) and all((row['kind'] != 'OTHER' and row['sha256'] is not None and (row['bytes'] is not None) and (0 < row['bytes'] < 16000000) and (row['created_at_utc'] is not None) and (c.utc(c.DRIVE_RECOVERY['window_start']) <= c.utc(row['created_at_utc']) <= c.utc(c.DRIVE_RECOVERY['window_end'])) for row in entries)) and (originals[0]['sha256'] == reuse['raw_sha256']) and (originals[0]['bytes'] == c.DRIVE_RECOVERY['raw_bytes']) and (not normalized or normalized[0]['sha256'] == reuse['normalized_sha256']), 'EXTERNAL_ORPHAN_INVENTORY_CLOSURE')
        c.require(isinstance(data, dict) and set(data) == {'capture_failed_run_id', 'rows_sha256', 'codec', 'mode', 'created_at_utc', 'lookup_observed_at_utc', 'inventory_sha256', 'original_create_outcome'} and (data['capture_failed_run_id'] == c.DRIVE_RECOVERY['run_id']) and (type(data['capture_failed_run_id']) is int) and isinstance(data['rows_sha256'], str) and c.re.fullmatch('[0-9a-f]{64}', data['rows_sha256']) and (data['mode'] in {'EXISTING_VERIFIED', 'DERIVED_NEW'}) and (data['codec'] in {'EXISTING_GZIP_VERIFIED', 'GZIP_FILENAME_EMPTY_MTIME0_LEVEL9'}) and (data['codec'] == {'DERIVED_NEW': 'GZIP_FILENAME_EMPTY_MTIME0_LEVEL9', 'EXISTING_VERIFIED': 'EXISTING_GZIP_VERIFIED'}[data['mode']]) and (data['original_create_outcome'] == 'UNKNOWN') and (data['inventory_sha256'] == c.digest(c.encoded(evidence))) and isinstance(data['created_at_utc'], str) and isinstance(data['lookup_observed_at_utc'], str) and (c.utc(evidence['observed_at_utc']) <= c.utc(data['lookup_observed_at_utc'])) and (c.utc(data['created_at_utc']) <= c.utc(data['lookup_observed_at_utc']) <= c.utc(reuse['derived_at_utc'])) and (not normalized or (data['mode'] == 'EXISTING_VERIFIED' and c.utc(data['created_at_utc']) == c.utc(normalized[0]['created_at_utc']))) and (normalized or data['mode'] != 'EXISTING_VERIFIED' or (not c.utc(c.DRIVE_RECOVERY['window_start']) <= c.utc(data['created_at_utc']) <= c.utc(c.DRIVE_RECOVERY['window_end']))) and (data['mode'] != 'DERIVED_NEW' or c.utc(evidence['observed_at_utc']) <= c.utc(data['created_at_utc'])), 'EXTERNAL_MATERIAL_PROVENANCE')


def validate_external_authorization(c, auth):
    if c.has_source_revision(auth):
        return c._revision_module(auth).validate(c._module(), auth)
    from tools import alpaca_sip_private_backfill_v1 as cap
    ex = auth['external_cohort']
    revised = isinstance(ex, dict) and 'named_recovery' in ex
    drive_revised = isinstance(ex, dict) and 'drive_recovery' in ex
    material_revised = isinstance(ex, dict) and 'materialization_recovery' in ex
    native_revised = isinstance(ex, dict) and 'native18_recovery' in ex
    c.require(isinstance(ex, dict) and set(ex) == {'scope', 'input_csv', 'intake_manifest_sha256', 'receipt_dedupe_sha256', 'prior_authorization', 'prior_epochs', 'proof_reference'} | ({'named_recovery'} if revised else set()) | ({'drive_recovery'} if drive_revised else set()) | ({'materialization_recovery'} if material_revised else set()) | ({'native18_recovery'} if native_revised else set()), 'EXTERNAL_AUTHORIZATION')
    scope = cap.external_scope(ex['scope'])
    c.require(isinstance(ex['input_csv'], str), 'EXTERNAL_COHORT_SCHEMA')
    raw = ex['input_csv'].encode('utf-8')
    names = cap.external_cohort(raw)
    c.require(c.digest(raw) == scope['input_sha256'], 'EXTERNAL_COHORT_HASH')
    for key in ('intake_manifest_sha256', 'receipt_dedupe_sha256'):
        c.require(isinstance(ex[key], str) and c.re.fullmatch('[0-9a-f]{64}', ex[key]), 'EXTERNAL_INPUT_PROOF')
    prior = ex['prior_authorization']
    c.require(isinstance(prior, dict) and set(prior) == c.AUTH_FIELDS and (c.validate_authorization(prior) == c.CONTINUATION['auth']), 'EXTERNAL_BUDGET_ORIGIN')
    fixed = c.AUTH_FIELDS - {'schema', 'limits', 'expected_master', 'code_pins', 'account_permission_reference', 'owner_permission_id', 'credential_binding'}
    c.require(all((auth[k] == prior[k] for k in fixed)) and auth['expected_master'] != prior['expected_master'] and (auth['owner_permission_id'] is None or c.digest(auth['owner_permission_id'].encode()) == c.CONTINUATION['bindings']['owner_sha256']) and (auth['credential_binding'] == c.CONTINUATION['bindings']['credential_binding']) and (prior['owner_permission_id'] in (None, auth['owner_permission_id'])) and (prior['credential_binding'] in (None, auth['credential_binding'])), 'EXTERNAL_BUDGET_ORIGIN')
    c.require(isinstance(ex['proof_reference'], str) and c.re.fullmatch('https://github\\.com/wscha231/r1000-quant-engine/issues/448#issuecomment-[0-9]+', ex['proof_reference']) and (auth['account_permission_reference'] == ex['proof_reference']), 'EXTERNAL_PROOF_REFERENCE')
    epochs = ex['prior_epochs']
    c.require(isinstance(epochs, list) and len(epochs) <= 1, 'EXTERNAL_EPOCH_LIMIT')
    for previous in epochs:
        c.require(isinstance(previous, dict) and isinstance(previous.get('external_cohort'), dict) and (previous['external_cohort'].get('prior_epochs') == []), 'EXTERNAL_EPOCH_LIMIT')
        c.validate_authorization(previous)
        old = previous['external_cohort']
        c.require(old['prior_authorization'] == prior and old['scope']['namespace'] != scope['namespace'] and all((auth[k] == previous[k] for k in fixed)) and set(names).isdisjoint(cap.external_cohort(old['input_csv'].encode())), 'EXTERNAL_RECOLLECTION')
    c.require(c.digest(cap.SEED.read_bytes().replace(b'\r\n', b'\n')) == c.SEED_SHA, 'CAMPAIGN_SEED')
    c.require(set(names).isdisjoint(cap.cohort(cap.SEED.read_bytes())[:c.CONTINUATION['examined']]), 'EXTERNAL_RECOLLECTION')
    c.require(len(c.encoded(auth)) <= 15000, 'CAMPAIGN_CONTROL_SIZE')
    if native_revised:
        previous = c.external_previous(auth)
        c.require(isinstance(ex['native18_recovery'], dict) and set(ex['native18_recovery']) == {'settlement_sha256'} and isinstance(ex['native18_recovery']['settlement_sha256'], str) and c.re.fullmatch('[0-9a-f]{64}', ex['native18_recovery']['settlement_sha256']) and (not (revised or drive_revised or material_revised)) and (len(ex['prior_epochs']) == 1) and (scope == dict(task_key='R1000-DISCOVERY-EXPANSION-INTAKE-20261017', namespace='top500-20261017', input_sha256=cap.STORAGE_QUARANTINE['input_sha256'])) and (len(names) == 417) and (names[76:80] == ['VLO', 'MFG', 'BP', 'BTI']) and (c.validate_authorization(previous) == c.NATIVE18_RECOVERY['prior_auth']) and (auth['expected_master'] not in (previous['expected_master'], c.NATIVE18_MASTER)) and (ex['proof_reference'] != previous['external_cohort']['proof_reference']), 'EXTERNAL_NATIVE18_RECOVERY')
    elif material_revised:
        recovery = ex['materialization_recovery']
        c.require(drive_revised and revised and isinstance(recovery, dict) and (set(recovery) == {'prior_capture_source', 'failed_run_id', 'failed_receipt_sha256', 'checkpoint_sha256', 'examined'}), 'EXTERNAL_MATERIAL_RECOVERY')
        source = recovery['prior_capture_source']
        c.require(isinstance(source, dict) and set(source) == {'expected_master', 'code_pins', 'proof_reference'} and (ex['prior_epochs'] == []), 'EXTERNAL_MATERIAL_RECOVERY')
        previous = c.external_previous(auth)
        c.require(c.validate_authorization(previous) == c.MATERIALIZATION_RECOVERY['prior_auth'] and previous['expected_master'] == c.MATERIALIZATION_RECOVERY['master'] and all((recovery[k] == c.MATERIALIZATION_RECOVERY[v] and type(recovery[k]) is type(c.MATERIALIZATION_RECOVERY[v]) for k, v in (('failed_run_id', 'run_id'), ('failed_receipt_sha256', 'receipt_sha256'), ('checkpoint_sha256', 'checkpoint_sha256'), ('examined', 'examined')))) and all((ex[k] == previous['external_cohort'][k] for k in ex if k not in ('materialization_recovery', 'proof_reference'))) and all((auth[k] == previous[k] for k in c.AUTH_FIELDS - {'schema', 'expected_master', 'code_pins', 'account_permission_reference'})) and (auth['expected_master'] != previous['expected_master']) and (ex['proof_reference'] != previous['external_cohort']['proof_reference']), 'EXTERNAL_MATERIAL_RECOVERY')
    elif drive_revised:
        recovery = ex['drive_recovery']
        c.require(revised and isinstance(recovery, dict) and (set(recovery) == {'prior_capture_source', 'failed_run_id', 'failed_receipt_sha256', 'checkpoint_sha256', 'examined'}), 'EXTERNAL_DRIVE_RECOVERY')
        source = recovery['prior_capture_source']
        c.require(isinstance(source, dict) and set(source) == {'expected_master', 'code_pins', 'proof_reference'} and (ex['prior_epochs'] == []), 'EXTERNAL_DRIVE_RECOVERY')
        previous = c.external_previous(auth)
        c.require(c.validate_authorization(previous) == c.DRIVE_RECOVERY['prior_auth'] and previous['expected_master'] == c.DRIVE_RECOVERY['master'] and all((recovery[k] == c.DRIVE_RECOVERY[v] and type(recovery[k]) is type(c.DRIVE_RECOVERY[v]) for k, v in (('failed_run_id', 'run_id'), ('failed_receipt_sha256', 'receipt_sha256'), ('checkpoint_sha256', 'checkpoint_sha256'), ('examined', 'examined')))) and all((ex[k] == previous['external_cohort'][k] for k in ex if k not in ('drive_recovery', 'proof_reference'))) and all((auth[k] == previous[k] for k in c.AUTH_FIELDS - {'schema', 'expected_master', 'code_pins', 'account_permission_reference'})) and (auth['expected_master'] != previous['expected_master']) and (ex['proof_reference'] != previous['external_cohort']['proof_reference']), 'EXTERNAL_DRIVE_RECOVERY')
    elif revised:
        recovery = ex['named_recovery']
        c.require(isinstance(recovery, dict) and set(recovery) == {'prior_capture_source', 'failed_run_id', 'failed_receipt_sha256', 'checkpoint_sha256', 'examined'}, 'EXTERNAL_NAMED_RECOVERY')
        source = recovery['prior_capture_source']
        c.require(isinstance(source, dict) and set(source) == {'expected_master', 'code_pins', 'proof_reference'} and (ex['prior_epochs'] == []), 'EXTERNAL_NAMED_RECOVERY')
        previous = c.external_previous(auth)
        c.require(c.validate_authorization(previous) == c.NAMED_RECOVERY['prior_auth'] and all((recovery[k] == c.NAMED_RECOVERY[v] and type(recovery[k]) is type(c.NAMED_RECOVERY[v]) for k, v in (('failed_run_id', 'run_id'), ('failed_receipt_sha256', 'receipt_sha256'), ('checkpoint_sha256', 'checkpoint_sha256'), ('examined', 'examined')))) and all((ex[k] == previous['external_cohort'][k] for k in ex if k not in ('named_recovery', 'proof_reference'))) and all((auth[k] == previous[k] for k in c.AUTH_FIELDS - {'schema', 'expected_master', 'code_pins', 'account_permission_reference'})) and (auth['expected_master'] != previous['expected_master']) and (ex['proof_reference'] != previous['external_cohort']['proof_reference']), 'EXTERNAL_NAMED_RECOVERY')

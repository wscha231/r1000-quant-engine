"""Pure CP128 terms and forecast arithmetic; all I/O stays in the existing controller.

The controller context preserves existing validation/mock seams during the bounded
source split; live external execution must pin this module transitively.
"""

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


def renewed(auth):
    return auth.get("schema")=="r1000-sip-external-cohort-authorization-v8"


def corrective(auth):
    return renewed(auth) or auth.get("schema")=="r1000-sip-external-cohort-authorization-v7"


def corrective_auth(c,auth):
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
        else:
            c.require(transition["run_id"] in state["named_failures"] and state["examined"]==transition["examined"]
                and state["parent"]==transition["checkpoint_sha256"],"EXTERNAL_RECOVERY_PARENT")
            expected=transition["run_id"]
    elif version<len(transitions):
        c.require(transitions[version].get("kind") in ("SOURCE_REVISION","CORRECTIVE_SOURCE","VALIDITY_SOURCE")
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
    return isinstance(value,dict) and value.get("schema")==REFUSAL_SCHEMA


def price_observations(c,auth,observed):
    receipts,durations=observed["cohort_receipts"],observed["cohort_durations"]
    c.require(len(receipts)==len(durations),"EXTERNAL_FORECAST_SAMPLE")
    if not corrective(auth):
        c.require(not any(is_refusal(r) for r in receipts),"EXTERNAL_REFUSAL_EVIDENCE")
        return receipts,durations
    refs=[(r,t) for r,t in zip(receipts,durations) if is_refusal(r)]
    c.require(refs==[(refusal_value(c,auth["external_cohort"]["scope"]),185)],"EXTERNAL_REFUSAL_EVIDENCE")
    pairs=[(r,t) for r,t in zip(receipts,durations) if not is_refusal(r)]
    return [r for r,t in pairs],[t for r,t in pairs]


def calibration_basis(c,auth,observed):
    runs=observed["runs"];current=observed.get("current_run")
    current_nonce=observed.get("current_nonce")
    prior_count=22 if corrective(auth) else 21
    c.require(len(runs)==prior_count+(current is not None)
        and [r["id"] for r in runs[:21]]==BASIS_IDS,"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    if corrective(auth):
        r=runs[21]
        c.require(r.get("id")==REFUSAL_RUN and r.get("run_attempt")==1 and r.get("head_sha")==V6_SOURCE
            and r.get("display_title")=="a1-sip "+REFUSAL_NONCE and r.get("status")=="completed"
            and r.get("conclusion")=="failure" and observed["active_seconds"]==5123,
            "EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    else:
        c.require(observed["active_seconds"]==4938,"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    if current is not None:
        r=runs[-1]
        c.require(isinstance(observed.get("external_proof"),dict)
            and isinstance(observed["external_proof"].get("proof_updated_utc"),str),"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
        c.require(type(current) is int and current>0 and current not in BASIS_IDS+[REFUSAL_RUN]
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


def verify_refusal(c,auth,run,jobs,artifacts,source_blobs,log):
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
    # The sealed hash identifies the reviewed pre-RuntimeMeter guard path; it
    # does not establish a packet trace or zero total platform cost.
    canonical=log.replace(b"\r\n",b"\n").rstrip(b"\n")+b"\n\n"
    c.require(len(canonical)<=1_000_000 and c.digest(canonical)==REFUSAL_LOG,"EXTERNAL_REFUSAL_LOG")
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


def time_acceptance(c, auth, observed, forecast):
    c.require(c.has_source_revision(auth),"EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    validate(c,auth)
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
        and (not renewed(auth) or c.utc(VALIDITY_START)<=c.utc()) and c.utc()<expiry(c,auth),
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
    return result


def verify_transition(c, state, used, active):
    c.require(state["examined"] == 128 and state["parent"] == CP
        and state["receipts"] and c.digest(c.encoded(state["receipts"][-1])) == RECEIPT
        and used == USED and active == 4938,"EXTERNAL_SOURCE_REVISION_PARENT")


def verify_marker(c, auth, value, observed):
    c.require(value.get("source_revision_policy_sha256") == policy_hash(c),"EXTERNAL_SOURCE_REVISION_RECEIPT")
    if value["examined_before"] == 128:
        expected = time_acceptance(c,auth,observed,c.external_forecast(auth,observed))
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


def verify_external_proof(c, auth, expected, comment, grant=None):
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
        grant_proof = verify_validity_grant(c, auth, grant)
        c.require(grant_proof['author_id'] == author['id'] and c.utc(grant_proof['created_at']) <= created and (c.utc(VALIDITY_START) <= created < c.utc(VALIDITY_END)), 'EXTERNAL_VALIDITY_PROOF')
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

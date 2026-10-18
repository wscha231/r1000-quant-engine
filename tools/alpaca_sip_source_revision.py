"""Pure CP128 terms and forecast arithmetic; all I/O stays in the existing controller.

The controller context preserves existing validation/mock seams during the bounded
source split; live external execution must pin this module transitively.
"""

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
    ex = dict(auth["external_cohort"])
    ex.pop("source_revision")
    ex["proof_reference"] = OLD_REFERENCE
    return dict(auth,schema="r1000-sip-external-cohort-authorization-v5",
                expected_master=OLD_SOURCE,code_pins=dict(OLD_PINS),
                account_permission_reference=OLD_REFERENCE,external_cohort=ex)


def validate(c, auth):
    ex = auth["external_cohort"]
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
    c.require(observed["examined"] == 128 and observed["parent_sha"] == CP
        and observed["used"] == USED and observed["active_seconds"] == 4938
        and len(observed["runs"]) == 21
        and [c.digest(c.encoded(r)) for r in observed["cohort_receipts"]] == SAMPLES
        and observed["cohort_durations"] == [274,305,275,255,380,372]
        and forecast["projected"] == PROJECTED and forecast["fits"] is False
        and type(forecast["active_seconds"]) is int and 0 < forecast["active_seconds"] <= 38748
        and forecast["dispatches"] == 10 and forecast["batch_sizes"] == [32]*9+[1]
        and forecast["margin"] == 1.25 and forecast["price_samples"] == 5
        and forecast["one_time_recovery_samples"] == 1 and forecast["price_processed"] == 124
        and all(forecast["projected"][k] <= observed["remaining"][k] for k in c.LIMITS)
        and 21+forecast["dispatches"] <= 40
        and observed["active_seconds"]+7800 <= c.active_limit(auth)
        and c.utc() < c.utc(c.CONTINUATION["first"])+c.timedelta(hours=48),
        "EXTERNAL_TIME_FORECAST_ACCEPTANCE")
    return dict(schema=POLICY["schema"],policy_sha256=policy_hash(c),checkpoint_sha256=CP,
                original_forecast_seconds=38748,accepted_forecast_seconds=forecast["active_seconds"],
                original_remaining_seconds=38262,forecast_fits=False,actual_limits_unchanged=True)


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
    receipts, durations = observed["cohort_receipts"], observed["cohort_durations"]
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


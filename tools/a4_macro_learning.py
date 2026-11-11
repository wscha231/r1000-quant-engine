"""Purged benchmark/sector relationship research and immutable monthly trials.

The caller supplies an externally pinned input policy and verified source
bindings. A boolean in an observation cannot authorize learning or promotion.
Existing expanding-window/HAC/BY mathematics are reused, not a portfolio fit.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from tools import a4_liquidity_analysis as analysis
from tools.a4_primary_sources import semantic_register
from tools import macro_technical_study as study
from tools import free_market_context as free
from tools.macro_history_sources import digest, encoded, exclusive
from tools.check_run287_do_not_repeat import evaluate_candidate, load_registry
from tools.daily_crisis_report_clock import mcal

SCHEMA = "a4-macro-learning-trial-v1"
MAX_TRIAL_BYTES = 32 * 1024**2
SAFETY = dict(causal_effect_identified=False, historical_pit_certified=False,
    automatic_promotion_allowed=False, eligible_for_selector=False,
    portfolio_weight_effect=0, target_book_write_allowed=False, orders_generated=False)
OUTCOMES = ("return", "maximum_drawdown", "realized_volatility")
FEATURES = {"funding:"+name: dict(family="FUNDING", kind="continuous") for name in analysis.SPREADS}
for _sid, _spec in {**analysis.SERIES, **semantic_register()}.items():
    if _spec[5] == "FUNDING": continue
    _logical, _, _freq, _, _, _family, _age = _spec
    _name = ("change_4_weeks:" if _freq == "weekly" else "change_1_month:" if _freq == "monthly" else "change_5_observations:")+_logical
    FEATURES[_name] = dict(family=_family, kind="release" if _freq != "daily" else "continuous")


def check(test, code): free.require(test, code)


def calendar_sessions(sessions, cutoff):
    check(type(sessions) is list and 2 <= len(sessions) <= 10000, "A4_LEARNING_SESSION_BUDGET")
    check(all(type(s) is dict and set(s) == {"session", "close_utc"} for s in sessions), "A4_SESSION_SCHEMA")
    dates = [free.iso_date(s["session"]).isoformat() for s in sessions]
    check(dates == sorted(set(dates)), "A4_SESSION_ORDER")
    schedule = mcal.get_calendar("NYSE").schedule(start_date=dates[0], end_date=dates[-1])
    check([d.date().isoformat() for d in schedule.index] == dates, "A4_SESSION_GRID")
    check(all(free.utc(s["close_utc"]) == t.to_pydatetime() for s,t in zip(sessions,schedule.market_close))
          and free.utc(sessions[-1]["close_utc"]) <= free.utc(cutoff), "A4_SESSION_CLOCK")
    return pd.DatetimeIndex(dates)


def validate_inputs(payload, policy, expected_policy_sha256, artifact_resolver):
    check(digest(encoded(policy)) == expected_policy_sha256, "A4_LEARNING_EXTERNAL_POLICY_PIN")
    check(policy.get("schema") == "a4-learning-input-policy-v1" and policy.get("purpose") == "MACRO_RELATIONSHIP_RESEARCH",
          "A4_LEARNING_POLICY")
    check(payload.get("schema") == "a4-macro-learning-inputs-v1" and digest(encoded(payload)) in policy.get("input_pins", []),
          "A4_LEARNING_INPUT_NOT_REVIEWED")
    cutoff = payload["cutoff"]
    check(free.utc(policy["available_at"]) <= free.utc(cutoff) < free.utc(policy["expires_at"]), "A4_LEARNING_POLICY_EXPIRED")
    sessions = calendar_sessions(payload["sessions"], cutoff)
    bindings = policy.get("source_bindings", {})
    observations, prices = payload.get("observations"), payload.get("prices")
    check(type(observations) is list and len(observations) <= 150000 and type(prices) is dict
          and set(prices) <= set(analysis.TARGETS), "A4_LEARNING_INPUT_BUDGET")
    originals = {r["original_sha256"] for r in observations}
    originals.update(r["original_sha256"] for rows in prices.values() for r in rows)
    check(callable(artifact_resolver) and len(originals) <= 128, "A4_LEARNING_ORIGINAL_RESOLVER")
    reserved=0
    primary_register = semantic_register()
    allowed_sources={"fred:"+sid for sid in analysis.SERIES}|{"frb:"+sid for sid in primary_register}|{"nyfed:"+sid for sid in ("SOFR","TGCR","EFFR")}|{"price:"+target for target in analysis.TARGETS}
    for sha in sorted(originals):
        binding = bindings.get(sha, {})
        source_ids=binding.get("source_ids")
        check(type(source_ids) is list and 0<len(source_ids)<=len(allowed_sources) and
              all(type(s) is str and s in allowed_sources for s in source_ids) and
              len(set(source_ids))==len(source_ids),"A4_LEARNING_SOURCE_MEMBERSHIP_SCHEMA")
        check(type(binding.get("size_bytes")) is int and 0<binding["size_bytes"]<=32*1024**2,
              "A4_LEARNING_SOURCE_SIZE_REQUIRED")
        reserved+=binding["size_bytes"]
        check(reserved<=64*1024**2,"A4_LEARNING_SOURCE_BYTE_BUDGET")
        check(all(type(binding.get(k)) is str and re.fullmatch(r"[a-f0-9]{64}",binding[k]) for k in
                  ("rights_evidence_sha256","source_receipt_sha256")),"A4_LEARNING_SOURCE_EVIDENCE_ID")
        check(binding.get("purpose") == "MACRO_RELATIONSHIP_RESEARCH"
              and binding.get("historical_use") in {"DATE_ARCHIVE_RESEARCH_ONLY", "FORWARD_CAPTURE_ONLY"}
              and binding.get("rights_evidence_sha256") in policy.get("reviewed_rights_pins", [])
              and binding.get("source_receipt_sha256") in policy.get("reviewed_source_receipt_pins", []),
              "A4_LEARNING_SOURCE_SCOPE_NOT_REVIEWED")
        if any(s.startswith('frb:') for s in source_ids):
            check(binding.get('historical_use') == 'FORWARD_CAPTURE_ONLY', 'A4_PRIMARY_HISTORY_NOT_PIT')
        raw = artifact_resolver(sha)
        check(type(raw) is bytes and len(raw)==binding["size_bytes"] and digest(raw) == sha, "A4_LEARNING_ORIGINAL_HASH")
    for row in observations:
        provider, _, sid=row["source_id"].partition(":")
        register = primary_register if provider == 'frb' else analysis.SERIES
        check(sid in register,"A4_LEARNING_SOURCE_ID")
        spec=register[sid]
        check(tuple(row.get(k) for k in ("logical_id","unit","frequency","measurement_basis","seasonal_basis","family","max_age_days"))==spec,
              "A4_LEARNING_SOURCE_SEMANTICS")
        free.number(row["value"])
        check(free.iso_date(row["observation_date"])<=free.utc(row["available_at"]).date(),
              "A4_LEARNING_OBSERVATION_AFTER_AVAILABILITY")
        check(free.iso_date(row["observation_date"])<=free.utc(row["collected_at"]).date(),
              "A4_LEARNING_OBSERVATION_AFTER_COLLECTION")
        check(free.utc(row["available_at"]) <= free.utc(cutoff), "A4_LEARNING_FUTURE_OBSERVATION")
        binding = bindings[row["original_sha256"]]
        check(row["source_id"] in binding.get("source_ids", []), "A4_LEARNING_SOURCE_BINDING")
        if binding["historical_use"] == "FORWARD_CAPTURE_ONLY":
            check(free.utc(row["available_at"]) >= free.utc(row["collected_at"]), "A4_LEARNING_BACKDATED_CURRENT")
    for target, rows in prices.items():
        check(type(rows) is list and len(rows)<=len(sessions),"A4_LEARNING_PRICE_BUDGET")
        for row in rows:
            check("price:"+target in bindings[row["original_sha256"]].get("source_ids",[]),
                  "A4_LEARNING_PRICE_SOURCE_BINDING")
    return sessions


def replay_features(observations, sessions):
    """One release sample per new reference period; revisions update the state.

    No daily repetition of a weekly/montly value in the training population.
    Current histories first collected now cannot populate older decisions.
    """
    state, index, latest_period, features = defaultdict(dict), 0, {}, {k: pd.Series(np.nan,index=pd.DatetimeIndex([s["session"] for s in sessions])) for k in FEATURES}
    ordered = sorted(observations, key=lambda r:(free.utc(r["available_at"]),r["logical_id"],r["observation_date"]))
    current = {}
    for session in sessions:
        cutoff = session["close_utc"]; changed = set()
        while index < len(ordered) and free.utc(ordered[index]["available_at"]) <= free.utc(cutoff):
            row = ordered[index]; index += 1
            check(free.iso_date(row["observation_date"])<=free.utc(row["available_at"]).date(),
                  "A4_LEARNING_OBSERVATION_AFTER_AVAILABILITY")
            check(free.iso_date(row["observation_date"])<=free.utc(row["collected_at"]).date(),
                  "A4_LEARNING_OBSERVATION_AFTER_COLLECTION")
            key, observed = row["logical_id"], row["observation_date"]
            old = state[key].get(observed)
            check(old is None or free.utc(old["available_at"]) != free.utc(row["available_at"]) or old == row,
                  "A4_LEARNING_CONFLICTING_VINTAGE")
            state[key][observed] = row; changed.add(key)
        for key in changed:
            history = [state[key][day] for day in sorted(state[key])]
            current[key] = analysis.summarize(history,cutoff)
            point = current[key]
            name = ("change_4_weeks:" if point["frequency"] == "weekly" else "change_1_month:" if point["frequency"] == "monthly" else "change_5_observations:")+key
            n = "4" if point["frequency"] == "weekly" else "1" if point["frequency"] == "monthly" else "5"
            if name in features and latest_period.get(name) != point["observation_date"]:
                features[name].loc[session["session"]] = point["changes"][n]["value"]
                latest_period[name] = point["observation_date"]
        for name,(left,right) in analysis.SPREADS.items():
            a,b = current.get(left),current.get(right); feature="funding:"+name
            if not a or not b: continue
            if a["observation_date"] != b["observation_date"] or latest_period.get(feature) == a["observation_date"]: continue
            if all(free.utc(cutoff).date()-free.iso_date(r["observation_date"]) <= timedelta(days=r["max_age_days"])
                   and r["value"] is not None for r in (a,b)):
                features[feature].loc[session["session"]] = (a["value"]-b["value"])*100
            latest_period[feature] = a["observation_date"]
    return features


def price_series(records, sessions, cutoff):
    check(type(records) is list and len(records) <= len(sessions), "A4_LEARNING_PRICE_BUDGET")
    values, basis = {}, set()
    closes = {r["session"]: free.utc(r["close_utc"]) for r in sessions}
    for r in records:
        session = r["session"]
        check(session in closes and session not in values, "A4_LEARNING_PRICE_SESSION")
        available = free.utc(r["available_at"])
        check(closes[session] <= available <= free.utc(cutoff), "A4_LEARNING_PRICE_CLOCK")
        value=free.number(r["value"])
        check(value is None or value>0, "A4_LEARNING_PRICE_VALUE")
        values[session]=value; basis.add(r["return_basis"])
    check(len(basis)<=1 and basis <= {"TOTAL_RETURN", "PROVIDER_ADJUSTED_CLOSE_PROXY"}, "A4_LEARNING_PRICE_BASIS")
    return pd.Series({pd.Timestamp(k):v for k,v in values.items()},dtype=float).reindex(
        pd.DatetimeIndex([r["session"] for r in sessions]))


def outcome_labels(close, horizon):
    result={"return":study.labels(close,horizon)}
    drawdown,volatility=np.full(len(close),np.nan),np.full(len(close),np.nan)
    values=close.to_numpy(float)
    for i in range(len(values)-horizon-1):
        # Include the decision row as in the incumbent path-integrity check.
        full=values[i:i+horizon+2]
        if not np.isfinite(full).all():continue
        path=full[1:]
        drawdown[i]=np.min(path/np.maximum.accumulate(path)-1)
        if horizon>=2:volatility[i]=np.std(np.diff(np.log(path)),ddof=1)*math.sqrt(252)
    result.update(maximum_drawdown=pd.Series(drawdown,index=close.index),
                  realized_volatility=pd.Series(volatility,index=close.index))
    return result


def insufficient(horizon, reason):
    return dict(horizon_sessions=horizon,status="INSUFFICIENT_EVIDENCE",blocker=reason,
        p_value=None,folds=[],oos_mse_improvement=None,family_q_value=None,
        oos_rows=0,nonoverlap_windows=0,effect_per_training_sd_pp=None,effect_ci95_pp=None,
        eligible_for_selector=False)


def fit_trial(payload, policy, expected_policy_sha256, artifact_resolver, *, registry=None):
    sessions=validate_inputs(payload,policy,expected_policy_sha256,artifact_resolver)
    features=replay_features(payload["observations"],payload["sessions"])
    context=policy.get("trial_identity",{})
    check(set(context)=={"signal","mechanism","book","window"},"A4_LEARNING_TRIAL_IDENTITY")
    preflight=evaluate_candidate(load_registry() if registry is None else registry,**context)
    check(preflight["allowed"],"A4_LEARNING_DO_NOT_REPEAT")
    rows=[]
    for target in analysis.TARGETS:
        close=price_series(payload["prices"].get(target,[]),payload["sessions"],payload["cutoff"])
        for horizon in analysis.HORIZONS:
            labels=outcome_labels(close,horizon)
            available_by_session={r["session"]:r["available_at"] for r in payload["prices"].get(target,[])}
            target_availability=[]
            for i in range(len(sessions)):
                if not available_by_session:
                    target_availability.append(None); continue
                path=[s.date().isoformat() for s in sessions[i:i+horizon+2]]
                clocks=[available_by_session.get(s) for s in path]
                target_availability.append(max(clocks,key=free.utc) if len(path)==horizon+2 and all(clocks) else None)
            for feature,series in features.items():
                for outcome in OUTCOMES:
                    values=labels[outcome]
                    valid=np.flatnonzero(np.isfinite(series.to_numpy(float)) & np.isfinite(values.to_numpy(float)))
                    minimum=60 if FEATURES[feature]["kind"]=="release" else 504
                    if len(valid)<minimum or study.independent_windows(valid,horizon)<20:
                        result=insufficient(horizon,"INDEPENDENT_MATURE_SAMPLE_TOO_SMALL")
                    else:
                        result=study.evaluate(series,values,horizon,kind=FEATURES[feature]["kind"],min_train=minimum,
                            label_available_at=target_availability, decision_times=[s["close_utc"] for s in payload["sessions"]])
                    result.update(target=target,feature=feature,outcome=outcome,
                                  outcome_unit="RETURN_FRACTION" if outcome!="realized_volatility" else "ANNUALIZED_VOLATILITY_FRACTION",
                                  evidence_family=FEATURES[feature]["family"])
                    if result.get("status")=="TESTED_SHADOW":
                        mask=np.isfinite(series.to_numpy(float)) & np.isfinite(values.to_numpy(float))
                        x,y=series.to_numpy(float)[mask],values.to_numpy(float)[mask]
                        mean,sd=float(np.mean(x)),float(np.std(x))
                        if sd>1e-12:
                            coefficients=np.linalg.lstsq(np.column_stack([np.ones(len(x)),(x-mean)/sd]),y,rcond=None)[0]
                            result["frozen_model"]=dict(mean=mean,sd=sd,intercept=float(coefficients[0]),coefficient=float(coefficients[1]),
                                last_training_decision=series.index[np.flatnonzero(mask)[-1]].date().isoformat(),
                                last_training_label_session=close.index[np.flatnonzero(mask)[-1]+horizon+1].date().isoformat())
                    rows.append(result)
    study.adjust_family(rows)
    result=dict(schema=SCHEMA,month=cadence(payload["cutoff"])["month"],cutoff=payload["cutoff"],
        input_sha256=digest(encoded(payload)),policy_sha256=expected_policy_sha256,
        feature_recipe_sha256=digest(encoded(FEATURES)),code_sha256=digest(Path(__file__).read_bytes()),
        math_dependencies={Path(module.__file__).name:digest(Path(module.__file__).read_bytes()) for module in (study,analysis)},
        targets=list(analysis.TARGETS),horizons=list(analysis.HORIZONS),outcomes=list(OUTCOMES),
        tests_declared=len(rows),results=rows,do_not_repeat=preflight,
        status="CHALLENGER_PROPOSAL_ONLY",promotion_state="INDEPENDENT_REVIEW_REQUIRED",**SAFETY)
    result["trial_sha256"]=digest(encoded(result))
    return result


def verify_trial(trial):
    check(trial.get("schema")==SCHEMA and trial.get("trial_sha256")==digest(encoded({k:v for k,v in trial.items() if k!="trial_sha256"})),
          "A4_LEARNING_TRIAL_HASH")
    check(all(trial.get(k)==v and type(trial.get(k)) is type(v) for k,v in SAFETY.items()),"A4_LEARNING_AUTHORITY")


def store_trial(trial, root):
    verify_trial(trial)
    raw=encoded(trial)
    check(len(raw)<=MAX_TRIAL_BYTES,"A4_LEARNING_TRIAL_SIZE")
    path=Path(root)/"trials"/(trial["trial_sha256"]+".json")
    exclusive(path,raw)
    check(path.read_bytes()==raw,"A4_LEARNING_TRIAL_READBACK")
    return dict(path="trials/"+path.name,sha256=digest(path.read_bytes()),trial_sha256=trial["trial_sha256"],
                accepted_model=False,durable_remote_verified=False)


def cadence(cutoff, *, previous_training_month=None, previous_week=None):
    day=free.utc(cutoff).astimezone(study.ZoneInfo("America/New_York")).date()
    iso=day.isocalendar(); week=f"{iso.year}-W{iso.week:02}"
    return dict(daily_diagnosis=True,weekly_score_due=previous_week!=week,
                monthly_trial_due=previous_training_month!=day.strftime("%Y-%m"),
                week=week,month=day.strftime("%Y-%m"),automatic_promotion_allowed=False)


def score_predictions(predictions, prices, sessions, cutoff):
    """Score fixed predictions only when the complete next-close path exists."""
    check(type(predictions) is list and len(predictions)<=100000,"A4_PREDICTION_BUDGET")
    index=calendar_sessions(sessions,cutoff); out=[]
    close_cache, outcome_cache, entry_cache = {}, {}, {}
    for prediction in predictions:
        check(prediction["horizon_sessions"] in analysis.HORIZONS and prediction["target"] in analysis.TARGETS
              and prediction["outcome"] in OUTCOMES,
              "A4_PREDICTION_SCOPE")
        check(free.utc(prediction["created_at"])<=free.utc(cutoff),"A4_FUTURE_PREDICTION")
        decision=pd.Timestamp(prediction["decision_session"])
        check(decision in index,"A4_PREDICTION_SESSION")
        i=index.get_loc(decision); h=prediction["horizon_sessions"]
        if i not in entry_cache:
            if i+1<len(sessions):entry_cache[i]=free.utc(sessions[i+1]["close_utc"])
            else:
                schedule=mcal.get_calendar("NYSE").schedule(start_date=decision.date(),end_date=decision.date()+timedelta(days=14))
                entry_cache[i]=schedule.market_close.iloc[1].to_pydatetime()
        entry_close=entry_cache[i]
        check(free.utc(sessions[i]["close_utc"])<=free.utc(prediction["created_at"])<entry_close,
              "A4_RETROSPECTIVE_PREDICTION")
        actual=None
        if i+h+1<len(sessions) and free.utc(sessions[i+h+1]["close_utc"])<=free.utc(cutoff):
            target=prediction["target"];key=(target,h)
            if target not in close_cache:close_cache[target]=price_series(prices.get(target,[]),sessions,cutoff)
            if key not in outcome_cache:outcome_cache[key]=outcome_labels(close_cache[target],h)
            actual=outcome_cache[key][prediction["outcome"]].iloc[i]
            actual=None if pd.isna(actual) else float(actual)
        estimate=free.number(prediction["estimate"])
        check(estimate is not None,"A4_PREDICTION_ESTIMATE")
        error=None if actual is None else (actual-estimate)**2
        check(error is None or math.isfinite(error),"A4_PREDICTION_SCORE_OVERFLOW")
        out.append(dict(prediction_sha256=digest(encoded(prediction)),status="MATURED" if actual is not None else "PENDING_OR_MISSING_PATH",
                        actual=actual,squared_error=error))
    return out


def forecast_release(report, trial, policy, expected_policy_sha256, *, created_at=None):
    """An externally reviewed fixed trial may explain a new report, never size it."""
    verify_trial(trial)
    check(digest(encoded(policy))==expected_policy_sha256 and trial["trial_sha256"] in policy.get("reviewed_trial_pins",[]),
          "A4_LEARNING_RELEASE_NOT_REVIEWED")
    check(free.utc(trial["cutoff"])<free.utc(report["cutoff"]) and
          free.utc(policy["available_at"])<=free.utc(report["cutoff"])<free.utc(policy["expires_at"]),
          "A4_LEARNING_RELEASE_CLOCK")
    created_at=created_at or report["cutoff"]
    check(free.utc(report["cutoff"])<=free.utc(created_at) and
          free.utc(policy["available_at"])<=free.utc(created_at)<free.utc(policy["expires_at"]),
          "A4_FORECAST_CREATION_CLOCK")
    check(trial["feature_recipe_sha256"]==digest(encoded(FEATURES)),"A4_LEARNING_RECIPE_CHANGED")
    check(trial.get("code_sha256")==digest(Path(__file__).read_bytes()) and trial.get("math_dependencies")==
          {Path(module.__file__).name:digest(Path(module.__file__).read_bytes()) for module in (study,analysis)},
          "A4_LEARNING_MODEL_CODE_CHANGED")
    points={"funding:"+key:r["value"] if r["status"]=="OBSERVED" else None
            for key,r in report["funding"]["spreads"].items()}
    panel={**report["liquidity"]["series"],**report["bank_credit"]["series"],**report["macro_direction_inputs"]}
    for logical,r in panel.items():
        if r is None: continue
        n="4" if r["frequency"]=="weekly" else "1" if r["frequency"]=="monthly" else "5"
        name=("change_4_weeks:" if r["frequency"]=="weekly" else "change_1_month:" if r["frequency"]=="monthly" else "change_5_observations:")+logical
        points[name]=r["changes"][n]["value"] if r["status"]=="OBSERVED" else None
    predictions=[]
    for row in trial["results"]:
        model=row.get("frozen_model"); value=points.get(row["feature"])
        if row["status"]!="SHADOW_CANDIDATE" or model is None or value is None: continue
        contribution=model["coefficient"]*(value-model["mean"])/model["sd"]
        estimate=model["intercept"]+contribution
        check(math.isfinite(estimate),"A4_NONFINITE_FORECAST")
        predictions.append(dict(target=row["target"],horizon_sessions=row["horizon_sessions"],outcome=row["outcome"],
            feature=row["feature"],evidence_family=row["evidence_family"],estimate=estimate,
            contribution_vs_training_mean=contribution,created_at=created_at,decision_session=report["session"],
            reviewed_trial_sha256=trial["trial_sha256"],qualified_company_er=False))
    if predictions:
        decision=free.iso_date(report["session"])
        schedule=mcal.get_calendar("NYSE").schedule(start_date=decision,end_date=decision+timedelta(days=14))
        check(len(schedule)>=2 and schedule.index[0].date()==decision and
              schedule.market_close.iloc[0].to_pydatetime()<=free.utc(created_at)<schedule.market_close.iloc[1].to_pydatetime(),
              "A4_PREDICTION_ENTRY_WINDOW")
    for horizon in report["horizon_outlook"]:
        matched=[p for p in predictions if p["target"]=="SPY" and p["horizon_sessions"]==horizon["horizon_sessions"] and p["outcome"]=="return"]
        signs={np.sign(p["contribution_vs_training_mean"]) for p in matched}
        horizon.update(direction="INSUFFICIENT_EVIDENCE" if not matched else "TAILWIND" if signs=={1} else "HEADWIND" if signs=={-1} else "MIXED",
            evidence=matched,contrary_evidence=[p for p in matched if p["contribution_vs_training_mean"]<0],
            blockers=[] if matched else ["NO_REVIEWED_CURRENT_INDEPENDENT_EVIDENCE"],independent_vote_count=None)
    report["historical_evidence"]=dict(status="REVIEWED_RELATIONSHIP_RESEARCH",trial_sha256=trial["trial_sha256"],
        predictions=predictions,causal_effect_identified=False)
    report["learning_provenance"]=dict(status="EXTERNALLY_REVIEWED_FIXED_RELEASE",policy_sha256=expected_policy_sha256,
        trial_sha256=trial["trial_sha256"],automatic_model_promotion_allowed=False)
    report.pop("content_sha256",None)
    from tools.chameleon_market_context_v2 import digest as report_digest
    report["content_sha256"]=report_digest(report)
    return predictions

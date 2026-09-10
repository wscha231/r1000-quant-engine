"""Chronological, self-financing USD research fund using the H1/H2 decision engine.

Only the simulator sees future market events. A decision receives one verified
as-of export packet and the account resulting from earlier fills. No provider,
broker, accepted ledger or production writer is called from this module.
"""
from __future__ import annotations
import copy
from datetime import datetime, time, timedelta, timezone
import hashlib
import math
from pathlib import Path

from tools.research_decision_v1 import engine, io
from tools.research_decision_v1.data import canonical, digest, number, timestamp, sessions, session_close, validate_persistable_sources, source_url
from tools.research_decision_v1.fund_metrics import metrics, execution_analysis, OBJECTIVE, select_cagr_trial, cagr_selection_pbo


SCHEMA = "fund-manager-replay-v1"
COMPARISON_SCHEMA = "fund-common-environment-v1"
COMPARISON_FIELDS = {"schema_version","base_currency","initial_cash_usd","start_at","end_date","markets",
    "decision_schedule","execution","benchmark_weights","opening_risk_free_hash","seed_closes_hash",
    "market_history_hash","common_input_history_hash"}
BOOK_SOURCE = "https://github.com/wscha231/r1000-quant-engine"


def require(condition, reason):
    if not condition: raise ValueError(reason)


def day_end(day):
    return datetime.combine(datetime.fromisoformat(day).date(), time(23, 59, 59), timezone.utc)


def scalar_evidence(record, cutoff, *, positive=False):
    source_url(record["source"])
    published, observed = timestamp(record["published_at"]), timestamp(record["observed_at"])
    require(published <= observed <= timestamp(cutoff), "fund_scalar_future_or_reversed")
    require(record["payload_hash"] == digest(record["value"]), "fund_scalar_hash")
    return number(record["value"], positive=positive)


def read_reference(root, reference):
    """Bounded descriptor read, canonical JSON hash, no path traversal/symlinks."""
    require(set(reference) == {"path", "sha256"}, "fund_reference_schema")
    path = Path(reference["path"])
    require(not path.is_absolute() and ".." not in path.parts and path.parts, "fund_reference_path")
    value = io.read_json(Path(root) / path)
    require(digest(value) == reference["sha256"], "fund_reference_hash")
    return value


def load_history(path, shard_sink=None):
    manifest = io.read_json(path)
    root = Path(path).absolute().parent
    require(manifest.get("schema_version") == SCHEMA, "fund_manifest_schema")
    # Event shards bound memory per input file; decisions are loaded only when
    # the clock reaches them. A changed reference cannot silently alter a run.
    def events():
        for reference in manifest["event_shards"]:
            shard = read_reference(root, reference)
            require(isinstance(shard, list), "fund_event_shard_not_list")
            validate_persistable_sources(shard,real=manifest["data_kind"] == "REAL")
            if shard_sink: shard_sink(reference,shard)
            yield from shard
    return manifest, events(), lambda reference: read_reference(root, reference)


def compare_development(spec, root):
    validate_persistable_sources(spec)
    require(spec["schema_version"] == "fund-cagr-development-v1", "fund_comparison_schema")
    trials = []
    kinds=set()
    common_basis = None
    for trial in spec["trials"]:
        result = read_reference(root, trial["result"])
        require(result["schema_version"] == SCHEMA and result["result_hash"] == digest({k:v for k,v in result.items() if k != "result_hash"}), "fund_comparison_result_identity")
        require(result["status"] == "COMPLETED_RESEARCH_REPLAY", "fund_comparison_incomplete_trial")
        require(result["objective"] == OBJECTIVE and result["costs_included"] is True, "fund_comparison_semantics")
        basis = result.get("comparison_basis")
        require(isinstance(basis,dict) and set(basis) == COMPARISON_FIELDS and basis.get("schema_version") == COMPARISON_SCHEMA and
                result.get("comparison_basis_hash") == digest(basis), "fund_comparison_basis_missing_or_invalid")
        require(basis["base_currency"] == "USD" and basis["initial_cash_usd"] == 100000. and
                timestamp(basis["start_at"]) == timestamp(result["start_at"]) and basis["end_date"] == result["end_date"],
                "fund_comparison_basis_result_mismatch")
        if common_basis is None:
            common_basis = basis
        else:
            require(basis == common_basis, "fund_comparison_environment_mismatch")
        kinds.add((result["data_kind"],result["evidence_mode"],result["evaluation_scope"]))
        trials.append({"trial_id": trial["trial_id"], "curve": result["equity_curve"],
                       "result_hash":result["result_hash"], "config_hash":result["config_hash"]})
    require(len(kinds) == 1, "fund_comparison_mixed_evidence")
    out = select_cagr_trial(trials, development_end=spec["development_end"], test_start=spec["test_start"],
                            max_drawdown=spec["max_drawdown"], registered_trial_ids=spec["registered_trial_ids"])
    out.update(comparison_basis=common_basis, comparison_basis_hash=digest(common_basis),
               source_authenticity_verified=False, oos_validated=False,
               trial_evidence=[{k:t[k] for k in ("trial_id","result_hash","config_hash")} for t in trials])
    if spec.get("pbo_blocks") is not None:
        columns = {t["trial_id"]: [b["equity_usd"]/a["equity_usd"]-1 for a,b in zip(t["curve"],t["curve"][1:])] for t in trials}
        out["cagr_selection_pbo"] = cagr_selection_pbo(columns, blocks=spec["pbo_blocks"])
    return out


class Fund:
    def __init__(self, manifest, config, decision_sink=None):
        self.spec, self.config = copy.deepcopy(manifest), copy.deepcopy(config)
        self.decision_sink = decision_sink
        require(manifest["schema_version"] == SCHEMA, "fund_manifest_schema")
        require(manifest["data_kind"] in {"REAL", "SYNTHETIC"}, "fund_data_kind")
        validate_persistable_sources(manifest, real=manifest["data_kind"] == "REAL")
        require(manifest["base_currency"] == "USD" and manifest["initial_cash_usd"] == 100000., "fund_initial_capital_contract")
        self.start, self.end = timestamp(manifest["start_at"]), day_end(manifest["end_date"])
        require(self.start < self.end, "fund_window_invalid")
        self.scope=manifest["evaluation_scope"]
        require(self.scope in {"MECHANICAL_PILOT","FULL_7_8_YEAR"}, "fund_evaluation_scope")
        if self.scope == "FULL_7_8_YEAR":
            duration=(self.end-self.start).total_seconds()/(365.25*86400)
            require(manifest["data_kind"] == "REAL" and 7 <= duration <= 8.1, "fund_full_history_length_or_kind")
        self.markets = manifest["markets"]
        require(self.markets and len(set(self.markets)) == len(self.markets) and set(self.markets) <= {"US", "KR"}, "fund_markets")
        require(manifest["decision_config_hash"] == digest(config), "fund_decision_config_hash")
        engine.validate_config(config)
        require(config.get("fund_manager_rebalance") is True, "fund_risk_rebalance_not_enabled")
        require(manifest["selection_objective"] == OBJECTIVE, "fund_objective")
        require(manifest["fill_mode"] == "next_close" and manifest["cash_carry_mode"] == "none", "fund_execution_contract")
        require(manifest["evidence_mode"] in {"CONTEMPORANEOUS_RECORDS", "RETROSPECTIVE_RECONSTRUCTION"}, "fund_evidence_mode")
        self.costs = {m: number(manifest["cost_bps"][m], nonnegative=True)/10000 for m in self.markets}
        require(all(self.costs[m] < .1 and config["one_way_cost_bps"][m] == manifest["cost_bps"][m]+(manifest["fx_conversion_bps"] if m == "KR" else 0.) for m in self.markets), "fund_cost_mismatch")
        self.fx_cost = number(manifest["fx_conversion_bps"], nonnegative=True)/10000
        require(self.fx_cost < .1, "fund_fx_cost_domain")
        self.max_pending = manifest["max_pending_sessions"]
        require(type(self.max_pending) is int and 1 <= self.max_pending <= 20, "fund_pending_lifetime")
        self.cash, self.fx = 100000., None
        self.shares, self.quotes, self.pending, self.receivables = {}, {}, {}, []
        self.delisted_ids = set()
        self.net_cash_flow, self.trades, self.action_log, self.decisions = {}, [], [], []
        self.fx_pnl = {}
        self.market_hasher, self.common_input_hasher = hashlib.sha256(), hashlib.sha256()
        self.previous, self.last_closes, self.benchmark_initial, self.benchmarks = None, {}, {}, {}
        self.cash_interest = 0.
        self.rate = scalar_evidence(manifest["opening_risk_free"], self.start.isoformat())
        require(self.rate > -1., "fund_rate_domain")
        self.rate_time, self.rf_growth = self.start, 1.
        self.weights = manifest["benchmark_weights"]
        require(set(self.weights) == set(self.markets) and math.isclose(sum(number(w,nonnegative=True) for w in self.weights.values()),1.,abs_tol=1e-12), "fund_benchmark_weights")
        self.daily, self.last_mark, self.last_rf_growth = [], self.start, 1.
        self.scheduled, self.seen_closes = set(), set()
        end_utc = self.end.isoformat()
        for market in self.markets:
            for day in sessions(market, self.start.date().isoformat(), end_utc):
                close = session_close(market, day)
                if self.start < close <= self.end: self.scheduled.add((market, day))

    def advance_rate(self, now):
        require(now >= self.rate_time, "fund_clock_reversed")
        self.rf_growth *= (1+self.rate)**((now-self.rate_time).total_seconds()/(365.25*86400))
        self.rate_time = now

    def usd(self, amount, sid):
        return amount if sid.startswith("US:") else amount/self.fx

    def equity(self):
        values = {sid: self.usd(q*self.quotes[sid]["close"], sid) for sid,q in self.shares.items() if q > 0}
        rights = sum(self.usd(r["amount_local"], r["security_id"]) for r in self.receivables)
        return self.cash+sum(values.values())+rights, values, rights

    def cash_flow(self, sid, amount):
        self.net_cash_flow[sid] = self.net_cash_flow.get(sid, 0.) + amount

    def pay_receivables(self, now):
        remaining = []
        for right in self.receivables:
            if timestamp(right["pay_at"]) > now: remaining.append(right); continue
            gross = self.usd(right["amount_local"], right["security_id"])
            fee = gross*self.fx_cost if right["security_id"].startswith("KR:") else 0.
            self.cash += gross-fee
            self.cash_flow(right["security_id"], gross-fee)
            self.action_log.append(dict(right, status="PAID", time=now.isoformat(), paid_usd=gross-fee, fx_cost_usd=fee))
        self.receivables = remaining

    def corporate_actions(self, actions, now, market):
        ids = set()
        for action in actions:
            require(action["action_id"] not in ids and not any(a.get("action_id") == action["action_id"] for a in self.action_log), "fund_duplicate_action")
            ids.add(action["action_id"])
            sid = action["security_id"]
            require(sid.startswith(market+":"), "fund_action_market")
            source_url(action["source"])
            require(timestamp(action["public_available_at"]) <= now and timestamp(action["effective_at"]) <= now, "fund_action_future")
            require(timestamp(action["effective_at"]).date() == now.date(), "fund_action_wrong_session")
            q = self.shares.get(sid, 0.)
            kind = action["kind"]
            if kind == "SPLIT":
                ratio = number(action["ratio"], positive=True)
                quantity = q*ratio
                whole = math.floor(quantity+1e-10)
                fraction = max(0., quantity-whole)
                if fraction:
                    # Fractional entitlements are receivables, never invented
                    # integer shares or a free immediate cash deposit.
                    price = number(action["cash_in_lieu_price"], nonnegative=True)
                    pay_at = action["pay_at"]
                    require(timestamp(pay_at) >= timestamp(action["effective_at"]), "fund_action_payment_order")
                    self.receivables.append(dict(action_id=action["action_id"],security_id=sid,amount_local=fraction*price,pay_at=pay_at))
                self.shares[sid] = float(whole)
                if sid in self.quotes: self.quotes[sid]["close"] /= ratio
                if sid in self.pending:
                    self.pending[sid]["target_quantity"] = math.floor(self.pending[sid]["target_quantity"]*ratio+1e-10)
            elif kind in {"DIVIDEND", "CASH_DELIST"}:
                amount = q*number(action["cash_per_share"], nonnegative=True)
                require(timestamp(action["pay_at"]) >= timestamp(action["effective_at"]), "fund_action_payment_order")
                if amount: self.receivables.append(dict(action_id=action["action_id"],security_id=sid,amount_local=amount,pay_at=action["pay_at"]))
                if kind == "CASH_DELIST":
                    self.shares.pop(sid, None)
                    self.delisted_ids.add(sid)
                    cancelled = self.pending.pop(sid, None)
                    if cancelled: self.trades.append(dict(cancelled, status="CANCELLED_CORPORATE_ACTION",time=now.isoformat()))
            else:
                raise ValueError("fund_unsupported_corporate_action")
            self.action_log.append(dict(action, time=now.isoformat(), status="APPLIED", entitled_quantity=q))

    def close(self, event, *, seed=False):
        now, market, day = timestamp(event["time"]), event["market"], event["session"]
        require(market in self.markets and session_close(market,day) == now, "fund_close_calendar_mismatch")
        source_url(event["source"])
        require(event["price_basis"] == "raw_unadjusted", "fund_execution_requires_raw_prices")
        require(event["corporate_actions_through"] == day, "fund_action_coverage_missing")
        require(timestamp(event["available_at"]) >= now, "fund_close_available_before_close")
        if seed:
            latest = sessions(market, (self.start-timedelta(days=15)).date().isoformat(), self.start.isoformat())
            require(latest and day == latest[-1] and not event["corporate_actions"], "fund_seed_not_latest_or_has_actions")
            require(market not in self.last_closes, "fund_duplicate_seed_market")
            require(timestamp(event["available_at"]) <= self.start, "fund_seed_not_available")
        else:
            require((market,day) in self.scheduled and (market,day) not in self.seen_closes, "fund_duplicate_or_out_of_window_close")
            self.seen_closes.add((market,day))
            self.advance_rate(now)
        if "KR" in self.markets or event.get("fx") is not None:
            new_fx = scalar_evidence(event["fx"], event["time"], positive=True)
            require((now-timestamp(event["fx"]["observed_at"])).total_seconds() <= 86400, "fund_fx_stale")
            if not seed and self.fx is not None:
                # Translate the pre-close holdings/rights first. Subsequent
                # local repricing uses the new FX rate; the cross term belongs
                # to local-asset P&L under this explicit sequential convention.
                local_values = {sid:q*self.quotes[sid]["close"] for sid,q in self.shares.items()
                                if q > 0 and sid.startswith("KR:")}
                for right in self.receivables:
                    sid=right["security_id"]
                    if sid.startswith("KR:"):
                        local_values[sid]=local_values.get(sid,0.)+right["amount_local"]
                for sid,value in local_values.items():
                    self.fx_pnl[sid]=self.fx_pnl.get(sid,0.)+value*(1/new_fx-1/self.fx)
            self.fx = new_fx
        if not seed:
            self.corporate_actions(event["corporate_actions"],now,market)
            self.pay_receivables(now)
        quoted = set()
        for quote in event["quotes"]:
            sid = quote["security_id"]
            require(sid.startswith(market+":") and sid not in quoted, "fund_quote_identity_or_duplicate")
            quoted.add(sid)
            require(type(quote["tradable"]) is bool, "fund_tradable_not_boolean")
            number(quote["close"], positive=True); number(quote["volume"], nonnegative=True)
            self.quotes[sid] = dict(quote, market=market,session=day,time=event["time"],available_at=event["available_at"])
        needed = {sid for sid,q in self.shares.items() if q > 0 and sid.startswith(market+":")} | {sid for sid in self.pending if sid.startswith(market+":")}
        require(needed <= quoted, "fund_held_or_pending_price_missing")
        if not seed: self.fill(now,market,quoted)
        self.last_closes[market] = day
        benchmark = number(event["benchmark_total_return_index"], positive=True)
        self.benchmarks[market] = benchmark
        if not seed:
            self.rate = scalar_evidence(event["risk_free"], event["time"])
            require(self.rate > -1, "fund_rate_domain")

    def fill(self, now, market, quoted):
        active = []
        for sid, order in list(self.pending.items()):
            if not sid.startswith(market+":"): continue
            require(timestamp(order["decision_at"]) < now, "fund_same_close_fill")
            order["attempted_sessions"] += 1
            quote = self.quotes[sid]
            if not quote["tradable"]:
                if order["attempted_sessions"] >= self.max_pending:
                    self.trades.append(dict(order,status="EXPIRED_HALTED",time=now.isoformat())); del self.pending[sid]
                continue
            current = self.shares.get(sid,0.)
            difference = order["target_quantity"]-current
            if difference == 0: del self.pending[sid]; continue
            # The order's capacity budget comes from prior H1 ADV, not a future
            # bar's price or volume. Event volume only rejects an impossible fill.
            max_quantity = min(math.floor(order["capacity_local"]/quote["close"]),math.floor(quote["volume"]*self.config["max_adv_participation"]))
            quantity = min(abs(difference),max_quantity)
            if quantity: active.append((sid,order,quantity,1 if difference>0 else -1))
        # Sells at this exchange close may fund buys at this same close. A sale
        # in a market that has not closed yet cannot fund these orders.
        for direction in (-1,1):
            items = sorted((r for r in active if r[3] == direction),key=lambda r:r[0])
            totals = {}
            for sid,order,quantity,sign in items:
                px = self.usd(self.quotes[sid]["close"],sid)
                fee_rate = self.costs[market]+(self.fx_cost if market == "KR" else 0.)
                totals[sid] = quantity*px*(1+fee_rate)
            scale = min(1.,self.cash/sum(totals.values())) if direction == 1 and sum(totals.values()) else 1.
            for sid,order,quantity,sign in items:
                if sign > 0: quantity=math.floor(quantity*scale+1e-10)
                if quantity <= 0: continue
                gross = self.usd(quantity*self.quotes[sid]["close"],sid)
                cost = gross*self.costs[market]
                fx_cost = gross*self.fx_cost if market == "KR" else 0.
                change = -sign*gross-cost-fx_cost
                require(self.cash+change >= -1e-7, "fund_borrowed_cash")
                self.cash=max(0.,self.cash+change)
                self.cash_flow(sid,change)
                self.shares[sid]=self.shares.get(sid,0.)+sign*quantity
                self.trades.append(dict(order,time=now.isoformat(),session=self.quotes[sid]["session"],
                    status="FILLED",quantity=quantity,side="BUY" if sign>0 else "SELL",price_local=self.quotes[sid]["close"],
                    fx_krw_per_usd=self.fx,gross_usd=gross,cost_usd=cost,fx_cost_usd=fx_cost,cash_after_usd=self.cash,
                    remaining_quantity=abs(order["target_quantity"]-self.shares[sid])))
                if self.shares[sid] == order["target_quantity"]: self.pending.pop(sid,None)
        for sid,order in list(self.pending.items()):
            if sid.startswith(market+":") and order["attempted_sessions"] >= self.max_pending:
                self.trades.append(dict(order,status="EXPIRED_UNFILLED_BALANCE",time=now.isoformat()))
                del self.pending[sid]

    def decide(self, event, packet):
        now = timestamp(event["time"])
        require(packet["decision_cutoff"] == event["time"], "fund_decision_cutoff_mismatch")
        require(packet["data_kind"] == self.spec["data_kind"], "fund_packet_data_kind")
        # Export outputs contain typed admission flags; validate the original
        # H1 input through replay_export instead of treating those flags as raw
        # credential-like user fields or accepting them as evidence.
        validate_persistable_sources({k:v for k,v in packet.items() if k != "market_exports"},
                                     real=self.spec["data_kind"] == "REAL")
        # Never turn a missing packet into a zero-return cash policy.
        require(packet["quality_bundle"] is not None, "fund_explicit_quality_required")
        require(packet["context"]["regime"]["input_hash"] == digest(packet["macro"]), "fund_macro_regime_binding")
        for observation in packet["macro"]:
            scalar_evidence(observation,event["time"])
            require(observation["vintage_at"] == observation["published_at"], "fund_macro_vintage_missing")
        require(packet["macro"], "fund_macro_missing")
        membership = packet["universe"]
        source_url(membership["source"])
        require(timestamp(membership["public_available_at"]) <= now, "fund_future_universe")
        require(membership["members_hash"] == digest(membership["members"]), "fund_universe_hash")
        require(len(membership["members"]) == len(set(membership["members"])), "fund_duplicate_universe_member")
        require(not set(membership["members"]) & self.delisted_ids, "fund_delisted_security_reentered")
        clean = [engine.replay_export(e) for e in packet["market_exports"]]
        require({e["market"] for e in clean} == set(self.markets), "fund_market_export_coverage")
        securities = {s["security_id"]:s for e in clean for s in e["securities"]}
        require(set(membership["members"]) <= set(securities), "fund_universe_export_missing")
        held = {sid for sid,q in self.shares.items() if q > 0}
        require(set(securities) == set(membership["members"]) | held, "fund_universe_membership_mismatch")
        require(all(e["data_kind"] == self.spec["data_kind"] and e["decision_cutoff"] == event["time"] for e in clean), "fund_export_identity")
        require(all(s["data_quality_pass"] for s in securities.values()), "fund_h1_inputs_incomplete")
        for sid,s in securities.items():
            quote=self.quotes.get(sid)
            require(quote is not None and timestamp(quote["available_at"]) <= now, "fund_decision_quote_unavailable")
            require(s["discovery"]["required_session"] == quote["session"] and
                    math.isclose(s["discovery"]["price"],quote["close"],rel_tol=1e-10), "fund_decision_price_reconciliation")
            require(math.isclose(s["blocks"]["price"]["payload"]["bars"][-1]["volume"],quote["volume"],rel_tol=1e-10),
                    "fund_decision_volume_reconciliation")
        ctx=copy.deepcopy(packet["context"])
        if "KR" in self.markets:
            require(math.isclose(number(ctx["fx"]["spot"],positive=True), self.fx,rel_tol=1e-10), "fund_decision_fx_reconciliation")
        if self.pending:
            # Reconcile the simulated open-order book before evaluating fresh
            # risk. A halted/partial old BUY cannot suppress a new risk-off or
            # thesis-exit decision. Filled shares and cash are never reset.
            for order in self.pending.values():
                self.trades.append(dict(order,status="CANCELLED_NEW_DECISION",time=event["time"]))
            self.pending.clear()
        nav,values,receivables=self.equity()
        spendable_nav=nav-receivables
        require(spendable_nav > 0, "fund_no_spendable_capital")
        # Distributions not paid yet contribute to NAV, but cannot buy stocks.
        ctx.pop("capital_krw",None)
        ctx.update(base_currency="USD",capital_base=spendable_nav,capital_is_assumption=True,
            mode="EXISTING_BOOK_PROPOSAL",decision_cutoff=event["time"],
            capital_basis="SIMULATED_NAV_EXCLUDING_UNPAID_RECEIVABLES",
            non_spendable_receivables_usd=receivables,
            eligible_security_ids=list(membership["members"]),
            book={"source":BOOK_SOURCE,"decision_cutoff":event["time"],"verified_at":event["time"],
                  "currency":"USD","positions":{sid:v/spendable_nav for sid,v in values.items()},
                  "cash_weight":self.cash/spendable_nav,"pending_orders":[]})
        result=engine.run_decisions(packet["market_exports"],ctx,self.config,self.previous,quality_bundle=packet["quality_bundle"])
        require(result["portfolio_proposal"]["ready"], "fund_decision_blocked")
        # A reviewed adverse thesis is valid exclusion evidence, not a missing
        # observation. An unreviewed company must not become a cash fallback.
        require(all(r["quality_assessment"]["schema_valid"] and r["quality_assessment"]["review_receipt_valid"] and
                    r["quality_assessment"]["company_assessment"] in {"pass","fail"} for r in result["ranking"]),
                "fund_research_coverage_incomplete")
        # Freeze common observations independently of strategy judgments and
        # packet file names. Held-only exports differ legitimately between
        # strategies; compare the full historical candidate universe instead.
        common={"time":now.isoformat(),"universe":membership,"macro":packet["macro"],
                "securities":[{"security_id":sid,"currency":securities[sid]["currency"],
                    "listing_board":securities[sid].get("listing_board"),
                    "blocks":{key:securities[sid]["blocks"][key] for key in ("price","financials")},
                    "optional":securities[sid].get("optional",{})} for sid in sorted(membership["members"])]}
        self.common_input_hasher.update((canonical(common)+"\n").encode("utf-8"))
        self.previous=result
        proposal=result["portfolio_proposal"]
        for row in proposal["rows"]:
            sid=row["security_id"]
            if row["action"] in {"HOLD","WAIT"}: continue
            target_usd=number(row["target_value_base"],nonnegative=True)
            target=math.floor(target_usd/self.usd(self.quotes[sid]["close"],sid)+1e-10)
            if sid not in membership["members"]: target=0
            if target == self.shares.get(sid,0.): continue
            self.pending[sid]={"security_id":sid,"decision_at":event["time"],"decision_hash":result["decision_hash"],
                "target_quantity":target,"attempted_sessions":0,
                "capacity_local":securities[sid]["discovery"]["adv20_local"]*self.config["max_adv_participation"],
                "reasons":row["reasons"]}
        record={"time":event["time"],"status":"DECIDED","packet_hash":digest(packet),
            "input_reference":copy.deepcopy(event["packet"]),
            "account_before":{"equity_usd":nav,"cash_usd":self.cash,"shares":copy.deepcopy(self.shares),
                              "receivables_usd":receivables,"spendable_nav_usd":spendable_nav},
            "decision":result,"submitted_orders":copy.deepcopy(self.pending)}
        if self.decision_sink:
            record["archive"]=self.decision_sink(record,packet)
            record["decision_hash"]=record.pop("decision")["decision_hash"]
        self.decisions.append(record)

    def mark(self, now):
        self.advance_rate(now)
        nav,values,rights=self.equity()
        require(nav > 0 and self.cash >= 0, "fund_insolvent")
        # KR benchmark values reflect the current USD translation even on a KR
        # holiday. Local index performance and FX are not mixed into one feed.
        benchmark=100000.*sum(self.weights[m]*self.benchmarks[m]*(1. if m == "US" else 1/self.fx)/self.benchmark_initial[m] for m in self.markets)
        all_ids=set(values)|set(self.net_cash_flow)|{r["security_id"] for r in self.receivables}
        pnl={sid: values.get(sid,0.)+self.net_cash_flow.get(sid,0.)+
             sum(self.usd(r["amount_local"],sid) for r in self.receivables if r["security_id"] == sid) for sid in all_ids}
        require(math.isclose(sum(pnl.values()),nav-100000.,abs_tol=1e-6), "fund_pnl_does_not_reconcile")
        self.daily.append({"time":now.isoformat(),"equity_usd":nav,"cash_usd":self.cash,
            "receivables_usd":rights,"holdings_usd":values,"shares":copy.deepcopy(self.shares),
            "risk_free_return":self.rf_growth/self.last_rf_growth-1.,"benchmark_equity_usd":benchmark,
            "cumulative_pnl_by_security_usd":pnl,"pending_order_count":len(self.pending),
            "cumulative_fx_pnl_by_security_usd":copy.deepcopy(self.fx_pnl),"fx_krw_per_usd":self.fx})
        self.last_mark,self.last_rf_growth=now,self.rf_growth

    def comparison_basis(self):
        """Observed common environment; hashes do not certify source authenticity."""
        return {"schema_version":COMPARISON_SCHEMA,"base_currency":"USD","initial_cash_usd":100000.,
            "start_at":self.start.isoformat(),"end_date":self.spec["end_date"],"markets":sorted(self.markets),
            "decision_schedule":copy.deepcopy(self.spec["decision_schedule"]),
            "execution":{"fill_mode":"next_close","price_basis":"raw_unadjusted","cash_carry_mode":"none",
                "cost_bps":{m:self.spec["cost_bps"][m] for m in self.markets},
                "fx_conversion_bps":self.spec["fx_conversion_bps"],"max_pending_sessions":self.max_pending,
                "max_adv_participation":self.config["max_adv_participation"],
                "accounting_policy":"integer_shares_receivables_same_close_netting_no_settlement_or_income_tax_v1",
                "pending_order_policy":"cancel_unfilled_remainder_before_each_new_decision"},
            "benchmark_weights":copy.deepcopy(self.weights),
            "opening_risk_free_hash":digest(self.spec["opening_risk_free"]),
            "seed_closes_hash":digest(self.spec["seed_closes"]),
            "market_history_hash":self.market_hasher.hexdigest(),
            "common_input_history_hash":self.common_input_hasher.hexdigest()}


def replay(manifest, events, config, packet_loader, *, now=None, decision_sink=None):
    """A blocked run retains diagnostics but publishes no partial performance."""
    fund=None
    try:
        fund=Fund(manifest,config,decision_sink)
        current=datetime.now(timezone.utc) if now is None else timestamp(now)
        require(fund.end < current, "fund_end_session_not_completed")
        schedule=manifest["decision_schedule"]
        if schedule["mode"] == "DAILY_AFTER_LAST_CLOSE":
            closes={}
            for market,day in fund.scheduled:
                closes[day]=max(closes.get(day,fund.start),session_close(market,day))
            expected=[(t+timedelta(minutes=5)).isoformat() for day,t in sorted(closes.items())]
        else:
            require(schedule["mode"] == "EXPLICIT_FROZEN" and fund.scope == "MECHANICAL_PILOT", "fund_decision_cadence")
            expected=schedule["times"]
        seeds=manifest["seed_closes"]
        require([timestamp(e["time"]) for e in seeds] == sorted(timestamp(e["time"]) for e in seeds), "fund_seed_order")
        for event in seeds:
            validate_persistable_sources(event,real=manifest["data_kind"] == "REAL")
            fund.close(copy.deepcopy(event),seed=True)
        require(set(fund.last_closes) == set(fund.markets), "fund_seed_market_coverage")
        fund.benchmark_initial={m:fund.benchmarks[m]*(1. if m == "US" else 1/fund.fx) for m in fund.markets}
        fund.daily=[{"time":fund.start.isoformat(),"equity_usd":100000.,"cash_usd":100000.,
                    "risk_free_return":0.,"benchmark_equity_usd":100000.,"shares":{},"holdings_usd":{},
                    "receivables_usd":0.,"cumulative_pnl_by_security_usd":{},"pending_order_count":0,
                    "cumulative_fx_pnl_by_security_usd":{},"fx_krw_per_usd":fund.fx}]
        previous=fund.start
        last_day=None
        decisions=0
        seen_times=set()
        actual_decisions=[]
        event_hasher=hashlib.sha256()
        for event in events:
            validate_persistable_sources(event,real=manifest["data_kind"] == "REAL")
            event_hasher.update((canonical(event)+"\n").encode("utf-8"))
            t=timestamp(event["time"])
            require(previous <= t <= fund.end and t >= fund.start, "fund_event_out_of_order_or_window")
            identity=(event["type"],event["time"],event.get("market"))
            require(identity not in seen_times, "fund_duplicate_event")
            seen_times.add(identity)
            if last_day and t.date() != last_day and day_end(last_day.isoformat()) > fund.last_mark:
                fund.mark(day_end(last_day.isoformat()))
            if event["type"] == "close":
                fund.market_hasher.update((canonical(event)+"\n").encode("utf-8"))
                fund.close(copy.deepcopy(event)); last_day=t.date()
            elif event["type"] == "decision":
                actual_decisions.append(t)
                require(len(actual_decisions) <= len(expected) and t == timestamp(expected[len(actual_decisions)-1]), "fund_decision_schedule_incomplete")
                # Copy only this packet. The economic decision function receives
                # neither the event iterator nor future price/quality snapshots.
                packet=packet_loader(event["packet"])
                fund.decide(event,copy.deepcopy(packet)); decisions+=1
            else: raise ValueError("fund_unknown_event")
            previous=t
        require(fund.seen_closes == fund.scheduled, "fund_exchange_session_coverage_incomplete")
        require(actual_decisions == [timestamp(t) for t in expected], "fund_decision_schedule_incomplete")
        require(decisions > 0, "fund_no_decisions")
        require(any(d["status"] == "DECIDED" for d in fund.decisions), "fund_no_completed_decisions")
        require(last_day and last_day.isoformat() == manifest["end_date"], "fund_final_close_missing")
        fund.mark(fund.end)
        result={"schema_version":SCHEMA,"status":"COMPLETED_RESEARCH_REPLAY","objective":OBJECTIVE,
            "data_kind":manifest["data_kind"],"manifest_hash":digest(manifest),"event_hash":event_hasher.hexdigest(),
            "event_hash_kind":"sha256_newline_delimited_canonical_json",
            "evaluation_scope":fund.scope,"start_at":manifest["start_at"],"end_date":manifest["end_date"],
            "config_hash":digest(config),"costs_included":True,"evidence_mode":manifest["evidence_mode"],
            "source_authenticity_verified":False,"historical_pit_certified":False,"oos_validated":False,
            "chronology_checks_completed":True,"production_promoted":False,"orders_allowed":False,
            "metrics":metrics(fund.daily),"equity_curve":fund.daily,"trades":fund.trades,
            "corporate_actions":fund.action_log,"decisions":fund.decisions,
            "pending_after_cutoff":list(fund.pending.values()),"receivables_after_cutoff":fund.receivables,
            "final_holdings":fund.daily[-1]["shares"],"final_cash_usd":fund.cash,
            "cash_carry_mode":"none","personal_income_tax_included":False,
            "fx_policy":"automatic_conversion_to_usd_at_observed_rate_with_declared_cost",
            "pending_order_policy":"cancel_unfilled_remainder_before_each_new_decision",
            "benchmark_policy":"fixed_initial_weights_buy_and_hold_total_return_indices_in_usd"}
        execution, attribution=execution_analysis(fund.daily,fund.trades,fund.action_log,fund.fx_pnl)
        result["metrics"].update(execution)
        result["pnl_attribution"]=attribution
        result["comparison_basis"]=fund.comparison_basis()
        result["comparison_basis_hash"]=digest(result["comparison_basis"])
        result["result_hash"]=digest(result)
        return result
    except (ValueError,KeyError,TypeError,OverflowError,ZeroDivisionError) as exc:
        # Data validation errors are controlled identifiers. Do not echo raw
        # source packets, paths or provider error bodies into a public report.
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith("fund_") else "fund_input_or_engine_validation_failed"
        kind=manifest.get("data_kind") if isinstance(manifest,dict) else None
        kind=kind if isinstance(kind,str) and kind in {"REAL","SYNTHETIC"} else None
        return {"schema_version":SCHEMA,"status":"BLOCKED","objective":OBJECTIVE,"metrics":None,
                "reason":reason,"data_kind":kind,"orders_allowed":False,
                "production_promoted":False,"completed_decisions":len(fund.decisions) if fund else 0,
                "last_completed_mark":fund.daily[-1]["time"] if fund and fund.daily else None}


def render(result):
    lines=["# USD fund research replay","",f"Status: {result['status']}",f"Objective: {OBJECTIVE}",
           f"Data kind: {result.get('data_kind')}","", "Research replay; no actual orders or promotion."]
    m=result.get("metrics")
    if not m: return "\n".join(lines+["",f"Blocked: {result.get('reason')}","Performance: unavailable.",""])
    lines += ["",f"Ending capital: ${m['ending_capital_usd']:,.2f}",f"CAGR: {m['cagr']:.2%}",
              f"Maximum drawdown: {m['max_drawdown']:.2%}",f"Sharpe (risk-free excess): {m['sharpe']}",
              f"Final cash: ${result['final_cash_usd']:,.2f}","",
              "Raw-price integer-share executions; dividends accrue on ex-date and become spendable on payment.",
              "Historical source authenticity and unused OOS status require independent evidence.",""]
    if result.get("pnl_attribution"):
        a=result["pnl_attribution"]
        lines += [f"Evidence: {result['evidence_mode']}; scope: {result['evaluation_scope']}",
            f"Window: {result['start_at']} through {result['end_date']}",
            f"Comparison basis: {result['comparison_basis_hash']}",
            f"Turnover (half gross / mean NAV): {m['turnover']:.2f}; annualized: {m['annualized_turnover']:.2f}",
            f"Partial fills: {m['partial_fill_count']}; pending at cutoff: {m['pending_at_cutoff_count']}","",
            "| Listing market | Local asset P&L (USD) | FX translation (USD) | Costs (USD) | Net P&L (USD) |",
            "|---|---:|---:|---:|---:|"]
        for market,row in sorted(a["by_listing_market"].items()):
            lines.append(f"| {market} | {row['local_asset_pnl_usd']:,.2f} | {row['fx_translation_pnl_usd']:,.2f} | {row['cost_usd']:,.2f} | {row['net_pnl_usd']:,.2f} |")
        lines += ["", "Local asset P&L includes distributions, lifecycle recovery and the price/FX interaction.",
                  "Listing market is not the company's economic country exposure. Cash earns zero under this policy.",
                  "Industry/theme/customer contribution and missed-winner/early-exit counterfactuals are not computed.",""]
    return "\n".join(lines)

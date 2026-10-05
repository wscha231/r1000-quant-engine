"""Frozen E2 mathematical and source-binding families, synthetic inputs only."""
from __future__ import annotations
import copy
import json
import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import nav_metrics_v2 as nav


def rows(values=(90.0, 95.0, 95.0)):
    days = ("2026-01-05", "2026-01-06", "2026-01-07")
    return [dict(session=d, timestamp=d+"T21:00:00Z", nav=value)
            for d,value in zip(days, values)]


def ref(value, identity, available):
    return dict(identity=identity, sha256=nav.digest(value), available_at=available)


def context(data, *, anchor_nav=100.0, anchor_time="2026-01-02T21:00:00Z",
            frequency="daily", rf_values=None, anchor_kind="PREFILL"):
    grid = [{k:r[k] for k in ("session", "timestamp")} for r in data]
    end = data[-1]["timestamp"]
    anchor = dict(kind=anchor_kind, timestamp=anchor_time, nav=anchor_nav)
    anchor["ref"] = ref(anchor.copy(), "synthetic-independent-anchor", anchor_time)
    rf_rows = []
    previous = anchor_time
    for r, value in zip(data, rf_values if rf_values is not None else [0.0]*len(data)):
        rf_rows.append(dict(start=previous, end=r["timestamp"], value=value, available_at=r["timestamp"]))
        previous = r["timestamp"]
    flow = dict(kind="ZERO_EXTERNAL_FLOW_ONLY", start=anchor_time, end=end, events=[])
    flow["ref"] = ref(flow.copy(), "synthetic-zero-flow-receipt", end)
    return dict(schema="nav-measurement-context-v2", frequency=frequency, cutoff=end,
                grid=dict(kind="INDEPENDENT_NYSE_REGULAR_CLOSE_GRID", rows=grid,
                          ref=ref(grid,"synthetic-independent-NYSE-grid",anchor_time)),
                anchor=anchor, nav_ref=ref(data,"synthetic-net-nav",end),
                risk_free=dict(kind="ACTUAL_INTERVAL_SIMPLE_RETURN", rows=rf_rows,
                               ref=ref(rf_rows,"synthetic-actual-interval-RF",end)),
                external_flows=flow)


def binding(data):
    points = [{k:r[k] for k in ("session","timestamp")} for r in data]
    return dict(rows=points, ref=ref(points,"synthetic-independent-valuation-clock",data[-1]["timestamp"]),
                cutoff=data[-1]["timestamp"])


def frame(data):
    import pandas as pd
    return pd.DataFrame([dict(date=r["session"], valuation_time_utc=r["timestamp"],
                              equity_usd=r["nav"], fill_mode="next_close") for r in data])


class NavMetricTests(unittest.TestCase):
    def assertBlocked(self, result):
        self.assertEqual(result["status"], nav.BLOCKED)
        self.assertFalse(result["metric_admission_complete"])
        for key in nav.METRIC_FIELDS:
            self.assertIsNone(result[key], key)
        self.assertFalse(result["valid_for_production"])
        json.dumps(result, allow_nan=False)

    def test_independent_anchor_includes_initial_loss_and_fee_once(self):
        for values, expected in (((90.0,90.0,90.0),-.1), ((99.0,99.0,99.0),-.01)):
            with self.subTest(values=values):
                data=rows(values); c=context(data)
                out=nav.calculate(data,c)
                self.assertEqual(out["status"],nav.COMPLETE)
                self.assertAlmostEqual(out["total_return"],expected)
                self.assertAlmostEqual(out["first_interval_return"],expected)
                self.assertAlmostEqual(out["max_dd"],expected)
                self.assertEqual(out["starting_capital_usd"],100.0)
                self.assertEqual(out["input_row_count"],3)
                self.assertEqual(out["cost_basis"],"SUPPLIED_NET_NAV_NO_SECOND_FEE")

    def test_elapsed_ACT_not_session_count_and_daily_RF_oracle(self):
        data=rows((101.0,103.02,106.1106))
        c=context(data,anchor_time="2026-01-04T21:00:00Z",rf_values=[.005,.006,.007])
        out=nav.calculate(data,c)
        self.assertEqual(out["status"],nav.COMPLETE)
        self.assertAlmostEqual(out["years"],3/365.25)
        self.assertAlmostEqual(out["sharpe_raw"],31.74901573277509,places=8)
        self.assertAlmostEqual(out["sharpe_excess_rf"],24.693678903269518,places=8)
        self.assertEqual(out["standard_deviation_ddof"],1)

    def test_anchor_missing_mismatch_naive_or_not_prior(self):
        data=rows()
        for mutate in ("missing","hash","first","naive","zero","bool","future_available"):
            with self.subTest(mutate=mutate):
                c=context(data)
                if mutate=="missing": c.pop("anchor")
                elif mutate=="hash": c["anchor"]["ref"]["sha256"]="0"*64
                elif mutate=="first": c["anchor"]["timestamp"]=data[0]["timestamp"]
                elif mutate=="naive": c["anchor"]["timestamp"]="2026-01-02T21:00:00"
                elif mutate=="zero": c["anchor"]["nav"]=0
                elif mutate=="bool": c["anchor"]["nav"]=True
                else: c["anchor"]["ref"]["available_at"]="2026-01-05T21:00:00Z"
                self.assertBlocked(nav.calculate(data,c))

    def test_original_rows_missing_extra_duplicate_shuffled_and_bad_clocks(self):
        data=rows(); c=context(data)
        cases=[data[:2],data+[data[-1]], [data[0],data[0],data[2]],data[::-1]]
        for key,value in (("session","2026-01-10"),("timestamp","2026-01-05T20:00:00Z"),
                          ("timestamp","2026-01-05T21:00:00"),("timestamp",None)):
            bad=copy.deepcopy(data);bad[0][key]=value;cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad):
                before=copy.deepcopy(bad)
                self.assertBlocked(nav.calculate(bad,c))
                self.assertEqual(bad,before)

    def test_strict_NAV_family_is_never_coerced_dropped_or_epsilon_repaired(self):
        for value in ("90",True,None,0,-1,float("inf"),float("nan")):
            with self.subTest(value=value):
                data=rows();c=context(data);data[1]["nav"]=value
                self.assertBlocked(nav.calculate(data,c))

    def test_independent_grid_hash_clocks_domain_and_order(self):
        for mutate in ("hash","kind","duplicate","order","future","not_close","late_receipt"):
            with self.subTest(mutate=mutate):
                data=rows();c=context(data);g=c["grid"]
                if mutate=="hash":g["ref"]["sha256"]="0"*64
                elif mutate=="kind":g["kind"]="PRICE_DATE_UNION"
                elif mutate=="duplicate":g["rows"][1]=g["rows"][0]
                elif mutate=="order":g["rows"]=g["rows"][::-1]
                elif mutate=="future":g["rows"][2]["timestamp"]="2026-01-08T21:00:00Z"
                elif mutate=="not_close":g["rows"][0]["timestamp"]="2026-01-05T15:00:00Z"
                else:g["ref"]["available_at"]=data[1]["timestamp"]
                self.assertBlocked(nav.calculate(data,c))

    def test_RF_missing_alignment_quote_identity_and_future_family(self):
        for mutate in ("missing","drop","duplicate","shift","extra","quote","hash","identity","future","nonfinite"):
            with self.subTest(mutate=mutate):
                data=rows();c=context(data); rf=c["risk_free"]
                if mutate=="missing":c.pop("risk_free")
                elif mutate=="drop":rf["rows"].pop()
                elif mutate=="duplicate":rf["rows"][1]=rf["rows"][0]
                elif mutate=="shift":rf["rows"][0]["start"]="2026-01-03T21:00:00Z"
                elif mutate=="extra":rf["rows"].append(rf["rows"][-1])
                elif mutate=="quote":rf["kind"]="ANNUAL_YIELD"
                elif mutate=="hash":rf["ref"]["sha256"]="0"*64
                elif mutate=="identity":rf["ref"]["identity"]=""
                elif mutate=="future":rf["rows"][0]["available_at"]="2026-01-06T21:00:00Z"
                else:rf["rows"][0]["value"]=float("inf")
                if mutate not in ("hash","identity","nonfinite","missing"):
                    rf["ref"]=ref(rf["rows"],"actual-rf",data[-1]["timestamp"])
                self.assertBlocked(nav.calculate(data,c))

    def test_external_deposit_withdrawal_untimed_and_scope_reject(self):
        for amount in (50.0,-50.0,True,None):
            with self.subTest(amount=amount):
                data=rows(); c=context(data);f=c["external_flows"]
                f["events"]=[dict(timestamp=data[0]["timestamp"],amount=amount)]
                f["ref"]=ref({k:v for k,v in f.items() if k!="ref"},"bound-flow",data[-1]["timestamp"])
                self.assertBlocked(nav.calculate(data,c))
        for mutate in ("missing","scope","untimed","kind","hash"):
            with self.subTest(mutate=mutate):
                data=rows();c=context(data);f=c["external_flows"]
                if mutate=="missing":c.pop("external_flows")
                elif mutate=="scope":f["start"]=data[0]["timestamp"]
                elif mutate=="untimed":f["events"]=[dict(amount=0.0)]
                elif mutate=="kind":f["kind"]="INFER_ZERO"
                else:f["ref"]["sha256"]="0"*64
                self.assertBlocked(nav.calculate(data,c))

    def test_zero_variance_and_one_interval_unavailable_without_epsilon(self):
        for data in (rows((100.,100.,100.)), rows((100.,))):
            with self.subTest(length=len(data)):
                out=nav.calculate(data,context(data))
                self.assertEqual(out["status"],nav.COMPLETE)
                self.assertIsNone(out["sharpe_raw"]);self.assertIsNone(out["sharpe_excess_rf"])
                self.assertIn(out["statistic_reasons"]["sharpe_raw"],("ZERO_VARIANCE","INSUFFICIENT_SAMPLE"))

    def test_derived_ratio_power_variance_overflow_is_bounded_finite_JSON(self):
        scenarios=[(rows((1e308,1e308,1e308)),1e-308,"2026-01-02T21:00:00Z"),
                   (rows((1e100,1e-100,1e100)),1e-100,"2026-01-02T21:00:00Z"),
                   (rows((2.,)),1.,"2026-01-05T20:59:59.999999Z")]
        for data,anchor,time in scenarios:
            with self.subTest(anchor=anchor,time=time):
                self.assertBlocked(nav.calculate(data,context(data,anchor_nav=anchor,anchor_time=time)))

    def test_weekly_declared_grid_and_annualization_are_diagnostic(self):
        data=[dict(session=d,timestamp=d+"T21:00:00Z",nav=n) for d,n in
              (("2026-01-09",101.),("2026-01-16",103.02),("2026-01-23",106.1106))]
        out=nav.calculate(data,context(data,frequency="weekly",rf_values=[.005,.006,.007]))
        self.assertEqual(out["status"],nav.COMPLETE)
        self.assertAlmostEqual(out["sharpe_excess_rf"],.014/.009*math.sqrt(52),places=8)
        self.assertEqual(out["annualization"],52)
        self.assertFalse(out["historical_pit_certified"])

    def test_UTC_equivalent_close_and_declared_early_close_controls(self):
        data=rows(); c=context(data)
        data[0]["timestamp"]="2026-01-05T16:00:00-05:00"
        c["nav_ref"]=ref(data,"same-NAV-source",c["cutoff"])
        self.assertEqual(nav.calculate(data,c)["status"],nav.COMPLETE)
        data=[dict(session="2026-11-27",timestamp="2026-11-27T18:00:00Z",nav=100.)]
        c=context(data,anchor_time="2026-11-25T21:00:00Z")
        self.assertEqual(nav.calculate(data,c)["status"],nav.COMPLETE)

    def test_actual_calendar_holidays_gaps_DST_and_false_halfday(self):
        for data in ([dict(session='2026-01-19',timestamp='2026-01-19T21:00:00Z',nav=100.)],
                     [rows()[0],rows()[2]],
                     [dict(session='2026-01-05',timestamp='2026-01-05T18:00:00Z',nav=100.)]):
            with self.subTest(data=data):
                self.assertBlocked(nav.calculate(data,context(data)))
        data=[dict(session='2026-07-01',timestamp='2026-07-01T20:00:00Z',nav=100.)]
        self.assertEqual(nav.calculate(data,context(data,anchor_time='2026-06-30T20:00:00Z'))['status'],nav.COMPLETE)

    def test_reference_byte_hash_and_future_clock_fail_closed(self):
        data=rows()
        for key in ("nav_ref","anchor","grid","external_flows","risk_free"):
            with self.subTest(key=key):
                c=context(data);r=c[key] if key=="nav_ref" else c[key]["ref"]
                r["available_at"]="2026-01-08T21:00:00Z"
                self.assertBlocked(nav.calculate(data,c))

    def test_resource_limits_and_duplicate_JSON_are_bounded(self):
        import tempfile
        data=rows();c=context(data)
        with patch.object(nav,"MAX_ROWS",2):
            self.assertBlocked(nav.calculate(data,c))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ctx.json";path.write_text('{"schema":1,"schema":2}',encoding="utf-8")
            with self.assertRaises(nav.MetricError):nav.load_context(path)

    def test_source_and_context_objects_are_not_mutated_by_measurement(self):
        data=rows();c=context(data);before=copy.deepcopy((data,c))
        out=nav.calculate(data,c)
        self.assertEqual((data,c),before)
        self.assertEqual(out["status"],nav.COMPLETE)
        self.assertFalse(out["valid_for_production"]);self.assertFalse(out["eligible_for_selector"])
        self.assertFalse(out["production_activation_allowed"]);self.assertFalse(out["fullrun_allowed"])
        self.assertNotEqual(out["status"],"completed")
        self.assertEqual(out["metric_mode"],nav.MODE)

    def test_canonical_serialization_budget_precedes_large_allocation(self):
        ordinary = {"z": [None, True, 2, -3.25, "a\n\U0001f600"], "a": {"q": "\\\""}}
        self.assertEqual(nav.encoded(ordinary), json.dumps(ordinary, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode())
        with patch.object(nav, "MAX_BYTES", 64):
            self.assertEqual(len(nav.encoded("x"*62)),64)
            for value in ("x"*65, {"x"*65: 1}, {"a":"x"*32,"b":"x"*32}, "\u0000"*11):
                with self.subTest(value_type=type(value).__name__):
                    calls=[]; original=json.dumps
                    def bounded(v,*a,**kw):
                        calls.append(v)
                        return original(v,*a,**kw)
                    with patch.object(nav.json,"dumps",side_effect=bounded):
                        with self.assertRaises(nav.MetricError):nav.encoded(value)
                    self.assertFalse(any(v is value for v in calls if type(v) is dict))
                    self.assertFalse(any(type(v) is str and len(v)>64 for v in calls))

    def test_frame_row_budget_precedes_records_copy(self):
        class Huge:
            def __len__(self):return 3
            def to_dict(self,*args):raise AssertionError("overbudget copied")
        with patch.object(nav,"MAX_ROWS",2):
            with self.assertRaisesRegex(nav.MetricError,"ROW_BUDGET"):
                nav.frame_rows(Huge(),date_column="date",nav_column="equity_usd")
            small=frame(rows()[:2])
            self.assertEqual(len(nav.frame_rows(small,date_column="date",nav_column="equity_usd")),2)

    def test_regular_context_byte_and_JSON_family_preserves_inputs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"context.json"
            for raw,valid in ((b'{}',True),(b'{}'+b' '*62,True),(b'',False),
                              (b'{}'+b' '*63,False),(b'{"x":1,"x":2}',False),
                              (b'{"x":NaN}',False),(b'['*18+b'0'+b']'*18,False)):
                with self.subTest(size=len(raw),raw=raw[:20]),patch.object(nav,"MAX_BYTES",64):
                    path.write_bytes(raw)
                    if len(raw)>64:
                        with patch.object(nav.os,"open",side_effect=AssertionError("overcap opened")), \
                             patch.object(Path,"read_bytes",side_effect=AssertionError("overcap eagerly read")), \
                             patch.object(nav.json,"loads",side_effect=AssertionError("overcap decoded")):
                            with self.assertRaises(nav.MetricError):nav.load_context(path)
                    elif valid:self.assertEqual(nav.load_context(path),{})
                    else:
                        with self.assertRaises(nav.MetricError):nav.load_context(path)
                    self.assertEqual(path.read_bytes(),raw)

    def test_context_nonregular_inputs_are_refused_before_open(self):
        import os,stat,tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);file=root/"ctx";file.write_bytes(b'{}')
            for path in (root,root/"missing"):
                with self.subTest(path=path.name),patch.object(nav.os,"open",side_effect=AssertionError("opened")):
                    with self.assertRaises(nav.MetricError):nav.load_context(path)
            for mode in (stat.S_IFIFO,stat.S_IFCHR,stat.S_IFSOCK,stat.S_IFLNK):
                with self.subTest(mode=mode),patch.object(nav.os,"lstat",return_value=SimpleNamespace(st_mode=mode)), \
                     patch.object(nav.os,"open",side_effect=AssertionError("special opened")):
                    with self.assertRaisesRegex(nav.MetricError,"CONTEXT_NOT_REGULAR"):nav.load_context(file)
            alias=root/"hardlink";os.link(file,alias)
            self.assertEqual(nav.load_context(alias),{})
            with patch.object(nav.os,"fstat",return_value=SimpleNamespace(st_mode=stat.S_IFIFO)), \
                 patch.object(nav.os,"read",side_effect=AssertionError("raced special file read")):
                with self.assertRaisesRegex(nav.MetricError,"CONTEXT_NOT_REGULAR"):nav.load_context(file)
            if hasattr(os,"mkfifo"):
                fifo=root/"fifo";os.mkfifo(fifo)
                with patch.object(nav.os,"open",side_effect=AssertionError("FIFO opened")):
                    with self.assertRaises(nav.MetricError):nav.load_context(fifo)
                link=root/"symlink";link.symlink_to(file)
                with self.assertRaises(nav.MetricError):nav.load_context(link)
            self.assertEqual(file.read_bytes(),b'{}')

    def test_windows_reserved_boundary_has_Python312_fallback(self):
        # Remove only the optional newer helper; the native 3.12 fallback remains exercised.
        saved=getattr(nav.os.path,"isreserved",None)
        if saved is not None:delattr(nav.os.path,"isreserved")
        try:
            for path in ('NUL','C:\\tmp\\CON.txt','C:\\tmp\\ctx:stream','C:\\tmp\\ctx.',
                         'C:\\tmp\\ctx ','\\\\.\\pipe\\ctx','\\\\?\\C:\\ctx'):
                with self.subTest(path=path):self.assertTrue(nav._windows_reserved(path))
            self.assertFalse(nav._windows_reserved('C:\\tmp\\ctx.json'))
        finally:
            if saved is not None:setattr(nav.os.path,"isreserved",saved)

    def test_context_read_errors_close_real_handles(self):
        import os,tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ctx";path.write_bytes(b'{}');fds=[];original=os.open
            def opened(*args,**kwargs):
                fd=original(*args,**kwargs);fds.append(fd);return fd
            for phase in ("open","fstat","read"):
                with self.subTest(phase=phase):
                    target="open" if phase=="open" else phase
                    with patch.object(nav.os,"open",side_effect=OSError("denied") if phase=="open" else opened), \
                         patch.object(nav.os,target,side_effect=OSError("denied")) if phase!="open" else patch.object(nav,"MAX_BYTES",nav.MAX_BYTES):
                        with self.assertRaisesRegex(nav.MetricError,"CONTEXT_INPUT_IO"):nav.load_context(path)
                    for fd in fds:
                        with self.assertRaises(OSError):os.fstat(fd)
                    fds.clear()
            close=os.close
            def failed_close(fd):close(fd);raise OSError("close failed")
            with patch.object(nav.os,"close",side_effect=failed_close):
                with self.assertRaisesRegex(nav.MetricError,"CONTEXT_INPUT_IO"):nav.load_context(path)
            self.assertEqual(path.read_bytes(),b'{}')

    def test_context_growth_short_read_and_replacement_are_bounded(self):
        import os,tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ctx";path.write_bytes(b'{}')
            for kind in ("growth","short","replace","changed_size"):
                with self.subTest(kind=kind):
                    reads=[];original=os.read;initial=os.stat(path)
                    def read(fd,n):
                        reads.append(n)
                        if kind=="growth":return b'x'*n
                        if kind=="short":return b''
                        return original(fd,n)
                    original_stat=os.lstat;count=0
                    def lstat(p):
                        nonlocal count
                        out=original_stat(p);count+=1
                        if kind=="replace" and count>1:
                            return SimpleNamespace(st_dev=out.st_dev,st_ino=out.st_ino+1,
                                                   st_size=out.st_size,st_mtime_ns=out.st_mtime_ns)
                        return out
                    original_fstat=os.fstat;fcalls=0
                    def fstat(fd):
                        nonlocal fcalls
                        out=original_fstat(fd);fcalls+=1
                        if kind=="changed_size" and fcalls>1:
                            return SimpleNamespace(st_dev=out.st_dev,st_ino=out.st_ino,
                                                   st_size=out.st_size+1,st_mtime_ns=out.st_mtime_ns)
                        return out
                    with patch.object(nav,"MAX_BYTES",64),patch.object(nav.os,"read",side_effect=read), \
                         patch.object(nav.os,"lstat",side_effect=lstat),patch.object(nav.os,"fstat",side_effect=fstat):
                        with self.assertRaises(nav.MetricError):nav.load_context(path)
                    self.assertLessEqual(sum(reads),65 if kind=="growth" else 130)
                    self.assertEqual(path.read_bytes(),b'{}')

    def test_loaded_future_clock_remains_blocked_without_input_repair(self):
        import tempfile
        data=rows();c=context(data);c["grid"]["ref"]["available_at"]="2026-01-08T21:00:00Z"
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ctx";raw=nav.encoded(c);path.write_bytes(raw)
            self.assertBlocked(nav.calculate(data,nav.load_context(path)))
            self.assertEqual(path.read_bytes(),raw)


    def test_consumed_frame_projection_bounds_without_copying_auxiliary_cells(self):
        import pandas as pd
        data=rows(); c=context(data); f=frame(data)
        huge='unused'*10000
        for i in range(40): f['unused_'+str(i)]=[huge]*3
        before=f.copy(deep=True)
        real_to_dict=pd.DataFrame.to_dict
        widths=[]
        def observed(obj,*a,**kw):
            widths.append(len(obj.columns))
            if len(obj.columns)>3: raise AssertionError('untouched auxiliary columns copied')
            return real_to_dict(obj,*a,**kw)
        with patch.object(pd.DataFrame,'to_dict',observed):
            out=nav.calculate_frame(f,c)
        self.assertEqual(out['status'],nav.COMPLETE,out)
        self.assertTrue(all(w<=3 for w in widths))
        pd.testing.assert_frame_equal(f,before)
        for kind in ('missing_date','missing_nav','duplicate_date','duplicate_nav','duplicate_clock','huge_date','huge_clock','huge_nav'):
            with self.subTest(kind=kind):
                bad=frame(data)
                if kind.startswith('missing'): bad=bad.drop(columns='date' if kind.endswith('date') else 'equity_usd')
                elif kind.startswith('duplicate'):
                    col={'duplicate_date':'date','duplicate_nav':'equity_usd','duplicate_clock':'valuation_time_utc'}[kind]
                    bad=pd.concat([bad,bad[[col]]],axis=1)
                else:
                    col={'huge_date':'date','huge_clock':'valuation_time_utc','huge_nav':'equity_usd'}[kind]
                    bad[col]=bad[col].astype(object);bad.loc[0,col]='X'*257
                with patch.object(pd.DataFrame,'to_dict',side_effect=AssertionError('copy before cell admission')):
                    out=nav.calculate_frame(bad,c)
                self.assertBlocked(out)
        with patch.object(nav,'MAX_BYTES',128), patch.object(pd.DataFrame,'to_dict',side_effect=AssertionError('copy before cumulative budget')):
            out=nav.calculate_frame(frame(data),c)
        self.assertBlocked(out)
        self.assertEqual(out['reason'],'RESOURCE_BYTES')

    def test_bound_receipt_covers_every_actual_clock_before_window_slice(self):
        data=rows();f=frame(data)
        for mutation in ('cutoff','available','both','naive','missing'):
            with self.subTest(mutation=mutation):
                b=binding(data);c=context(data[:1]);c['cutoff']=data[-1]['timestamp']
                if mutation in ('cutoff','both'): b['cutoff']=data[0]['timestamp']
                if mutation in ('available','both'): b['ref']['available_at']=data[0]['timestamp']
                if mutation=='naive': b['rows'][-1]['timestamp']='2026-01-07T21:00:00';b['ref']['sha256']=nav.digest(b['rows'])
                if mutation=='missing': b['rows'][-1].pop('timestamp');b['ref']['sha256']=nav.digest(b['rows'])
                out=nav.calculate_frame(f,c,valuation_binding=b,date_range=(data[0]['session'],data[0]['session']),label='is')
                self.assertBlocked(out)
        b=binding(data);c=context(data[:1]);c['cutoff']=data[-1]['timestamp']
        self.assertEqual(nav.calculate_frame(f,c,valuation_binding=b,date_range=(data[0]['session'],data[0]['session']),label='is')['status'],nav.COMPLETE)
        b['cutoff']='2026-01-07T16:00:00-05:00';b['ref']['available_at']=b['cutoff']
        self.assertEqual(nav.calculate_frame(f,c,valuation_binding=b,date_range=(data[0]['session'],data[0]['session']),label='is')['status'],nav.COMPLETE)


    def test_zero_flow_receipt_clock_covers_terminal_for_empty_and_zero_events(self):
        for frequency in ('daily','weekly'):
            data=rows() if frequency=='daily' else [dict(session=d,timestamp=d+'T21:00:00Z',nav=v) for d,v in zip(('2026-01-09','2026-01-16','2026-01-23'),(90.,95.,95.))]
            for count in (0,1,2):
                for kind in ('before_anchor','anchor','between','end_minus_microsecond','end','equivalent_UTC','after_end','future','naive','malformed','missing'):
                    with self.subTest(frequency=frequency,events=count,kind=kind):
                        c=context(data,frequency=frequency);end=nav.stamp(data[-1]['timestamp']);anchor=nav.stamp(c['anchor']['timestamp'])
                        c['cutoff']=(end+timedelta(hours=1)).isoformat();f=c['external_flows']
                        f['events']=[dict(timestamp=t,amount=0.) for t in (f['start'],f['end'])[:count]]
                        clocks=dict(before_anchor=anchor-timedelta(microseconds=1),anchor=anchor,between=end-timedelta(hours=1),
                                    end_minus_microsecond=end-timedelta(microseconds=1),end=end,equivalent_UTC=end,
                                    after_end=end+timedelta(minutes=30),future=end+timedelta(hours=1,microseconds=1))
                        clock=clocks.get(kind,end).isoformat()
                        if kind=='equivalent_UTC':clock=clock.replace('+00:00','Z')
                        if kind=='naive':clock=end.replace(tzinfo=None).isoformat()
                        if kind=='malformed':clock='not-a-clock'
                        f['ref']=ref({k:v for k,v in f.items() if k!='ref'},'actual-zero-scope',clock)
                        if kind=='missing':f['ref'].pop('available_at')
                        before=nav.encoded(c);original=copy.deepcopy(data);result=nav.calculate(data,c)
                        if kind in ('end','equivalent_UTC','after_end'):
                            self.assertEqual(result['status'],nav.COMPLETE,result);self.assertAlmostEqual(result['max_dd'],-.1)
                        else:
                            self.assertBlocked(result)
                            if kind in ('before_anchor','anchor','between','end_minus_microsecond'):
                                self.assertEqual(result['reason'],'FLOW_RECEIPT_PRECEDES_SCOPE_END')
                        self.assertEqual(nav.encoded(c),before);self.assertEqual(data,original)
                        self.assertFalse(result['eligible_for_selector']);self.assertFalse(result['fullrun_allowed'])
        c=context(rows());self.assertEqual(c['anchor']['ref']['available_at'],c['grid']['ref']['available_at'])
        self.assertEqual(nav.calculate(rows(),c)['status'],nav.COMPLETE)

    def test_RF_aggregate_receipt_covers_row_availability_without_terminal_rule(self):
        for early in (False,True):
            for kind in ('before_rows','at_rows','equivalent_UTC','after_rows','future','naive','missing','hash','row_future'):
                with self.subTest(early=early,kind=kind):
                    data=rows();c=context(data);c['cutoff']='2026-01-07T22:00:00Z';rf=c['risk_free']
                    if early:
                        for row in rf['rows']:row['available_at']=c['anchor']['timestamp']
                    last=max(nav.stamp(row['available_at']) for row in rf['rows']);clock=last.isoformat()
                    if kind=='before_rows':clock=(last-timedelta(microseconds=1)).isoformat()
                    elif kind=='equivalent_UTC':clock=last.isoformat().replace('+00:00','Z')
                    elif kind=='after_rows':clock=(last+timedelta(seconds=1)).isoformat()
                    elif kind=='future':clock='2026-01-07T22:00:01Z'
                    elif kind=='naive':clock=last.replace(tzinfo=None).isoformat()
                    elif kind=='row_future':rf['rows'][0]['available_at']='2026-01-05T21:00:01Z'
                    rf['ref']=ref(rf['rows'],'actual-interval-RF-receipt',clock)
                    if kind=='missing':rf['ref'].pop('available_at')
                    if kind=='hash':rf['ref']['sha256']='0'*64
                    before=nav.encoded(c);result=nav.calculate(data,c)
                    if kind in ('at_rows','equivalent_UTC','after_rows'):
                        self.assertEqual(result['status'],nav.COMPLETE,result)
                        if early:self.assertLess(nav.stamp(clock),nav.stamp(data[-1]['timestamp']))
                    else:
                        self.assertBlocked(result)
                        if kind=='before_rows':self.assertEqual(result['reason'],'RF_RECEIPT_PRECEDES_ROW_AVAILABILITY')
                        if kind=='row_future':self.assertEqual(result['reason'],'RF_FUTURE')
                    self.assertEqual(nav.encoded(c),before)


if __name__ == "__main__":
    unittest.main(verbosity=2)


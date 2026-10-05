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




    def test_r6_real_selected_decoder_classes_at_exact_reader_boundary(self):
        import tempfile,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
        from tools import run_weekly_evaluation as weekly,run_broker_ledger_replay as broker
        from tools.execution_cost_model import load_paper_slippage
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cache=root/'cache';cache.mkdir();dest=root/'out';dest.mkdir()
            cases=[('CSV',b'a,b\n\xff,1\n','UnicodeDecodeError'),('CSV',b'a,b\n"unfinished','ParserError'),
                   ('CSV',b'','EmptyDataError'),('JSON',b'{"a":\xff}','UnicodeDecodeError'),
                   ('JSON',b'{','JSONDecodeError'),('PARQUET',b'bad parquet','ArrowInvalid'),
                   ('PARQUET_ATTR',b'\xff','UnicodeDecodeError'),('PARQUET_ATTR',b'{','JSONDecodeError')]
            for fmt,raw,cause in cases:
                roles=('target','weekly_csv','rate','slippage') if fmt=='CSV' else ('weekly_json',) if fmt=='JSON' else ('price','rate','slippage')
                for role in roles:
                    with self.subTest(format=fmt,role=role,cause=cause):
                        suffix='.parquet' if fmt.startswith('PARQUET') else '.json' if fmt=='JSON' else '.csv'
                        path=cache/weekly.px_cache_name('AAA') if role=='price' else root/(role+suffix)
                        if fmt=='PARQUET_ATTR':
                            table=pa.Table.from_pydict({'date':['2026-01-02'],'ticker':['AAA'],'side':['BUY'],'observed_slippage_bps':[1.]})
                            pq.write_table(table.replace_schema_metadata({b'PANDAS_ATTRS':raw}),path)
                        else:path.write_bytes(raw)
                        before=path.read_bytes();prior=dest/'metrics.research_v2.json';prior.write_bytes(b'prior');foreign=dest/'foreign';foreign.write_bytes(b'keep')
                        @nav.research_io_guard('measurement_context')
                        def invoke(*,measurement_context):
                            nav.observe_research_publication(dest,[prior.name],{path.resolve()},cache)
                            if role=='target':return broker.read_csv(path)
                            if role=='weekly_csv':return weekly._read_csv(path,strict_io=True)
                            if role=='weekly_json':return weekly._read_json(path,strict_io=True)
                            if role=='rate':return broker.load_cash_rate_series(broker.CashCarryConfig(mode='risk_free_rate',rate_path=path),cache)
                            if role=='slippage':return load_paper_slippage(path,strict_io=True)
                            return weekly.load_price_series(cache,'AAA',strict_io=True)
                        try:result=invoke(measurement_context={})
                        except Exception as exc:self.fail('Selected decoder escaped: '+type(exc).__name__)
                        self.assertBlocked(result);self.assertEqual(result['reason'],'RESEARCH_IO_FAILURE')
                        self.assertEqual(result['selected_input_cause'],cause)
                        self.assertEqual(result['selected_input_format'],'PARQUET' if fmt.startswith('PARQUET') else fmt)
                        self.assertEqual(result['selected_input_reason'],'SELECTED_INPUT_DECODE')
                        self.assertFalse(result['current_publication_complete']);self.assertFalse(result['cleanup_complete'])
                        self.assertIn(prior.name,result['uncleared_generated_outputs'])
                        self.assertEqual(prior.read_bytes(),b'prior');self.assertEqual(path.read_bytes(),before);self.assertEqual(foreign.read_bytes(),b'keep')

    def test_r6_explicit_shape_date_and_valid_optional_legacy_controls(self):
        import tempfile,pandas as pd
        from tools import run_weekly_evaluation as weekly,run_broker_ledger_replay as broker
        from tools.execution_cost_model import load_paper_slippage
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);latest=root/'latest';path=latest/'orchestrator'/'unified_target_latest.json';path.parent.mkdir(parents=True)
            for value in ([1],[],None,1,True,{'audit_checks':[1]},{'audit_checks':[]},{'audit_checks':'bad'}):
                with self.subTest(json_value=value):
                    path.write_text(json.dumps(value),encoding='utf-8');before=path.read_bytes()
                    @nav.research_io_guard('measurement_context')
                    def fresh(*,measurement_context):return weekly.build_freshness(latest,{}, {},10,strict_io=True)
                    try:result=fresh(measurement_context={})
                    except Exception as exc:self.fail('Input shape escaped: '+type(exc).__name__)
                    self.assertBlocked(result);self.assertEqual(result['selected_input_format'],'JSON')
                    self.assertEqual(result['selected_input_reason'],'SELECTED_INPUT_JSON_AUDIT_OBJECT' if isinstance(value,dict) else 'SELECTED_INPUT_JSON_OBJECT')
                    self.assertEqual(path.read_bytes(),before)
            for value in ({},{'audit_checks':None},{'audit_checks':{}},{'audit_checks':{'invested_amount':1.}}):
                with self.subTest(valid_json=value):
                    path.write_text(json.dumps(value));self.assertIsInstance(weekly.build_freshness(latest,{}, {},10,strict_io=True),dict)
            path.unlink();self.assertEqual(weekly._read_json(path,strict_io=True),{})
            csv=root/'slip.csv'
            for date in ('2026-99-99','2026-02-30','2025-02-29'):
                with self.subTest(invalid_date=date):
                    csv.write_text('date,ticker,side,observed_slippage_bps\n'+date+',AAA,BUY,1\n')
                    @nav.research_io_guard('measurement_context')
                    def slip(*,measurement_context):return load_paper_slippage(csv,strict_io=True)
                    try:result=slip(measurement_context={})
                    except Exception as exc:self.fail('Date admission escaped: '+type(exc).__name__)
                    self.assertBlocked(result);self.assertEqual(result['selected_input_cause'],'DateParseError')
                    self.assertEqual(result['selected_input_reason'],'SELECTED_INPUT_DATE')
                    from pandas._libs.tslibs.parsing import DateParseError
                    with self.assertRaises(DateParseError):load_paper_slippage(csv)
            for date in ('2024-02-29','2026-01-02','2026-01-02T12:00:00','2026-01-02T21:00:00Z','undated',''):
                with self.subTest(valid_or_existing_undated=date):
                    csv.write_text('date,ticker,side,observed_slippage_bps\n'+date+',AAA,BUY,1\n')
                    pd.testing.assert_frame_equal(load_paper_slippage(csv,strict_io=True),load_paper_slippage(csv))
            csv.write_text('date,ticker,side,observed_slippage_bps\n');self.assertTrue(load_paper_slippage(csv,strict_io=True).empty)
            self.assertTrue(load_paper_slippage(None,strict_io=True).empty)
            self.assertTrue(load_paper_slippage(root/'absent.csv').empty)
            self.assertTrue(weekly._read_csv(root/'optional.csv',strict_io=True).empty)
            self.assertTrue(weekly.load_price_series(root,'NONE',strict_io=True).empty)
            with patch.object(pd,'read_csv',side_effect=AssertionError('disabled rate was read')):
                self.assertTrue(broker.load_cash_rate_series(broker.CashCarryConfig(mode='none',rate_path=csv),root).empty)

    def test_r6_programming_backend_errors_and_original_os_diagnostics_propagate(self):
        import tempfile,pandas as pd,pyarrow as pa
        from tools import run_weekly_evaluation as weekly,run_broker_ledger_replay as broker
        from tools.execution_cost_model import load_paper_slippage
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'source.csv';path.write_bytes(b'a\n1\n')
            for error in (RuntimeError('programming'),TypeError('programming'),ValueError('options'),AssertionError('programming'),
                          pa.ArrowTypeError('unsupported'),pa.ArrowNotImplementedError('unsupported')):
                for role in ('weekly','target','rate','slippage'):
                    with self.subTest(error=type(error).__name__,role=role):
                        @nav.research_io_guard('measurement_context')
                        def invoke(*,measurement_context):
                            if role=='weekly':return weekly._read_csv(path,strict_io=True)
                            if role=='target':return broker.read_csv(path)
                            if role=='rate':return broker.load_cash_rate_series(broker.CashCarryConfig(mode='risk_free_rate',rate_path=path),root)
                            return load_paper_slippage(path,strict_io=True)
                        with patch.object(pd,'read_csv',side_effect=error),self.assertRaises(type(error)):invoke(measurement_context={})
            with patch.object(pd,'read_csv',side_effect=RuntimeError('legacy')):
                self.assertTrue(weekly._read_csv(path).empty);self.assertTrue(broker.read_csv(path).empty);self.assertTrue(load_paper_slippage(path).empty)
            @nav.research_io_guard('measurement_context')
            def denied(*,measurement_context):raise PermissionError(13,'private path must not be retained')
            result=denied(measurement_context={});self.assertBlocked(result)
            self.assertEqual(result['io_error_type'],'PermissionError');self.assertEqual(result['io_error_errno'],13)
            self.assertNotIn('selected_input_cause',result);self.assertNotIn('private path',json.dumps(result))
            @nav.research_io_guard('measurement_context')
            def late(*,measurement_context):raise pd.errors.ParserError('not at a selected reader')
            with self.assertRaises(pd.errors.ParserError):late(measurement_context={})

    def test_r6_decode_cleanup_disclosure_and_parquet_backend_negatives(self):
        import tempfile,pandas as pd,pyarrow as pa
        from tools import run_weekly_evaluation as weekly,run_broker_ledger_replay as broker
        from tools.execution_cost_model import load_paper_slippage
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.json';source.write_bytes(b'{');dest=root/'out';dest.mkdir();leaf=dest/'metrics.research_v2.json'
            foreign=dest/'foreign';foreign.write_bytes(b'keep');nested=dest/'archive';nested.mkdir();(nested/leaf.name).write_bytes(b'nested keep')
            for kind in ('safe','unlink_denied','lstat_denied','protected','nonregular'):
                with self.subTest(cleanup=kind):
                    if leaf.is_dir():leaf.rmdir()
                    else:leaf.unlink(missing_ok=True)
                    if kind=='nonregular':leaf.mkdir()
                    else:leaf.write_bytes(b'prior')
                    original_unlink=Path.unlink;original_lstat=nav.os.lstat
                    def unlink(p,*a,**kw):
                        if kind=='unlink_denied' and p==leaf:raise PermissionError(13,'denied')
                        return original_unlink(p,*a,**kw)
                    def lstat(p,*a,**kw):
                        if kind=='lstat_denied' and Path(p)==leaf:raise PermissionError(13,'denied')
                        return original_lstat(p,*a,**kw)
                    @nav.research_io_guard('measurement_context')
                    def invoke(*,measurement_context):
                        protected={source.resolve()}|({leaf.resolve()} if kind=='protected' else set())
                        nav.observe_research_publication(dest,[leaf.name],protected,root/'cache')
                        nav.authorize_research_cleanup(dest,[leaf.name],protected,root/'cache')
                        return weekly._read_json(source,strict_io=True)
                    try:
                        with patch.object(Path,'unlink',unlink),patch.object(nav.os,'lstat',lstat):result=invoke(measurement_context={})
                    except Exception as exc:self.fail('Cleanup decoder escaped: '+type(exc).__name__)
                    self.assertBlocked(result);self.assertEqual(result['selected_input_cause'],'JSONDecodeError')
                    self.assertFalse(result['current_publication_complete']);self.assertEqual(result['cleanup_complete'],kind=='safe')
                    if kind=='safe':self.assertFalse(leaf.exists())
                    elif kind=='protected':self.assertIn(leaf.name,result['cleanup_refused_inputs']);self.assertEqual(leaf.read_bytes(),b'prior')
                    else:self.assertIn(leaf.name,result['uncleared_generated_outputs']);self.assertTrue(leaf.exists())
                    self.assertEqual(source.read_bytes(),b'{');self.assertEqual(foreign.read_bytes(),b'keep');self.assertEqual((nested/leaf.name).read_bytes(),b'nested keep')
            parquet=root/'input.parquet';parquet.write_bytes(b'placeholder');cache=root/'cache';cache.mkdir();(cache/weekly.px_cache_name('AAA')).write_bytes(b'placeholder')
            for error in (ValueError('engine option'),TypeError('programming'),RuntimeError('programming'),pa.ArrowTypeError('unsupported'),pa.ArrowNotImplementedError('unsupported')):
                for role in ('price','rate','slippage'):
                    with self.subTest(backend=type(error).__name__,role=role):
                        @nav.research_io_guard('measurement_context')
                        def invoke(*,measurement_context):
                            if role=='price':return weekly.load_price_series(cache,'AAA',strict_io=True)
                            if role=='rate':return broker.load_cash_rate_series(broker.CashCarryConfig(mode='risk_free_rate',rate_path=parquet),cache)
                            return load_paper_slippage(parquet,strict_io=True)
                        with patch.object(pd,'read_parquet',side_effect=error),self.assertRaises(type(error)):invoke(measurement_context={})



class HostedR3BindingCalendarResourceTests(unittest.TestCase):
    """Finite source955 review families; synthetic NAV, actual offline calendar."""
    def assertClosed(self, out):
        self.assertEqual(out['status'], nav.BLOCKED, out)
        for key in nav.METRIC_FIELDS:
            self.assertIsNone(out[key])
        self.assertFalse(out['metric_admission_complete'])
        self.assertFalse(out['valid_for_production'])

    def assertBinding(self, out, value):
        self.assertEqual(out['status'], nav.COMPLETE, out)
        self.assertEqual(out.get('valuation_binding_provenance'),
                         dict(sha256=nav.digest(value), ref=value['ref'], cutoff=value['cutoff']))
        self.assertFalse(out['valid_for_production'])

    def test_complete_binding_provenance_precedes_window_and_covers_all_fields(self):
        data=rows(); f=frame(data); original=binding(data)
        full=context(data); full['cutoff']='2026-01-07T22:00:00Z'
        is_context=context(data[:1]); is_context['cutoff']=full['cutoff']
        observed=[]
        for mutation in ('none','identity','available','cutoff','both','order','UTC'):
            with self.subTest(mutation=mutation):
                b=copy.deepcopy(original)
                if mutation=='identity':b['ref']['identity']='another-actual-receipt'
                if mutation in ('available','both'):b['ref']['available_at']='2026-01-07T21:10:00Z'
                if mutation in ('cutoff','both','available'):b['cutoff']='2026-01-07T21:30:00Z'
                if mutation=='order':b=dict(reversed(list(b.items())))
                if mutation=='UTC':b['ref']['available_at']='2026-01-07T16:00:00-05:00'
                before=nav.encoded(b); source=f.copy(deep=True)
                results=[nav.calculate_frame(f,full,valuation_binding=b),
                         nav.calculate_frame(f,is_context,valuation_binding=b,
                                             date_range=(data[0]['session'],data[0]['session']),label='is')]
                observed.append(results[0].get('valuation_binding_provenance'))
                for out in results:self.assertBinding(out,b)
                self.assertEqual(results[0].get('valuation_binding_provenance'),results[1].get('valuation_binding_provenance'))
                self.assertEqual(nav.encoded(b),before); self.assertTrue(source.equals(f))
        self.assertEqual(observed[0],observed[5])
        for index in (1,2,3,6):
            with self.subTest(distinct_binding=index):self.assertNotEqual(observed[0],observed[index])
        absent=nav.calculate_frame(f,full)
        self.assertEqual(absent['status'],nav.COMPLETE)
        self.assertNotIn('valuation_binding_provenance',absent)
        self.assertEqual(absent,nav.calculate(data,full))
        for mutation in ('identity','hash','receipt','cutoff','point','shape'):
            with self.subTest(invalid=mutation):
                b=copy.deepcopy(original)
                if mutation=='identity':b['ref']['identity']=True
                elif mutation=='hash':b['ref']['sha256']='0'*64
                elif mutation=='receipt':b['ref']['available_at']=data[0]['timestamp']
                elif mutation=='cutoff':b['cutoff']='2026-01-07T22:00:01Z'
                elif mutation=='point':b['rows'][-1]['timestamp']='2026-01-07T21:00:01Z';b['ref']['sha256']=nav.digest(b['rows'])
                else:b['unexpected']=True
                self.assertClosed(nav.calculate_frame(f,is_context,valuation_binding=b,
                    date_range=(data[0]['session'],data[0]['session']),label='is'))

    def test_actual_broker_windows_and_weekly_export_complete_binding(self):
        import pandas as pd
        from tools import run_broker_ledger_replay as broker
        from tools import run_weekly_evaluation as weekly
        data=rows(); f=frame(data); b=binding(data)
        c=dict(full=context(data),is_=context(data[:2]),
               oos=context(data[2:],anchor_time=data[1]['timestamp'],anchor_nav=data[1]['nav'],anchor_kind='OOS_PREDECESSOR'),
               oos2=context(data[1:2],anchor_time=data[0]['timestamp'],anchor_nav=data[0]['nav'],anchor_kind='OOS_PREDECESSOR'))
        c['is']=c.pop('is_')
        for value in c.values():value['cutoff']=data[-1]['timestamp']
        for identity in ('actual-caller-receipt-1','actual-caller-receipt-2'):
            with self.subTest(identity=identity):
                b['ref']['identity']=identity; original=nav.encoded(b)
                out=broker.calc_metrics_with_oos(f,pd.DataFrame(),100.,
                    oos_start=data[2]['session'],oos2_start=data[1]['session'],oos2_end=data[1]['session'],
                    measurement_contexts=c,valuation_binding=b)
                self.assertEqual(out['status'],nav.COMPLETE,out)
                for label in ('full','is','oos','oos2'):self.assertBinding(out[label],b)
                curve=f.rename(columns={'date':'week_end_date','equity_usd':'equity'})
                wc=context(data,frequency='weekly')
                w=weekly.weekly_metrics(curve,'main',measurement_context=wc,valuation_binding=b)
                self.assertBinding(w,b)
                # These are the actual dictionaries exported by each caller.
                self.assertEqual(json.loads(json.dumps(out))['oos']['valuation_binding_provenance']['sha256'],nav.digest(b))
                self.assertEqual(json.loads(json.dumps(w))['valuation_binding_provenance']['sha256'],nav.digest(b))
                self.assertEqual(nav.encoded(b),original)

    def test_native_historical_and_modern_exact_close_positive_controls(self):
        import pandas_market_calendars as mcal
        for lo,hi in (('1952-09-26','1952-09-30'),('1973-12-31','1974-01-03'),
                      ('1951-06-08','1951-06-11'),('2026-11-27','2026-11-30')):
            schedule=mcal.get_calendar('NYSE').schedule(start_date=lo,end_date=hi)
            data=[dict(session=d.date().isoformat(),timestamp=t.isoformat(),nav=100.)
                  for d,t in schedule['market_close'].items()]
            for frequency in ('daily','weekly'):
                with self.subTest(lo=lo,hi=hi,frequency=frequency):
                    sample=data if frequency=='daily' else data[::2]
                    anchor=(nav.stamp(data[0]['timestamp'])-timedelta(days=1)).isoformat()
                    c=context(sample,anchor_time=anchor,frequency=frequency); before=nav.encoded(c)
                    out=nav.calculate(sample,c)
                    self.assertEqual(out['status'],nav.COMPLETE,out)
                    self.assertEqual(nav.encoded(c),before)
                    for row in sample:row['timestamp']=nav.stamp(row['timestamp']).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).isoformat()
                    self.assertEqual(nav.calculate(sample,context(sample,anchor_time=anchor,frequency=frequency))['status'],nav.COMPLETE)

    def test_historical_calendar_does_not_admit_invented_closes_or_grid_repairs(self):
        import pandas_market_calendars as mcal
        schedule=mcal.get_calendar('NYSE').schedule(start_date='1952-09-26',end_date='1952-09-30')
        original=[dict(session=d.date().isoformat(),timestamp=t.isoformat(),nav=100.)
                  for d,t in schedule['market_close'].items()]
        for mutation in ('second','minute','hour','date','naive','duplicate','reverse','gap','Sunday','future'):
            with self.subTest(mutation=mutation):
                data=copy.deepcopy(original); c=context(data,anchor_time='1952-09-25T18:00:00Z')
                if mutation in ('second','minute','hour'):
                    offset={'second':timedelta(seconds=1),'minute':timedelta(minutes=1),'hour':timedelta(hours=1)}[mutation]
                    data[0]['timestamp']=(nav.stamp(data[0]['timestamp'])+offset).isoformat()
                elif mutation=='date':data[0]['timestamp']='1952-09-25T19:00:00Z'
                elif mutation=='naive':data[0]['timestamp']='1952-09-26T15:00:00'
                elif mutation=='duplicate':data.insert(1,copy.deepcopy(data[0]))
                elif mutation=='reverse':data.reverse()
                elif mutation=='gap':data.pop(1)
                elif mutation=='Sunday':data.insert(1,dict(session='1952-09-28',timestamp='1952-09-28T16:00:00Z',nav=100.))
                else:c['cutoff']='1952-09-26T19:00:00Z'
                if mutation!='future':c=context(data,anchor_time='1952-09-25T18:00:00Z')
                self.assertClosed(nav.calculate(data,c))

    def test_predecode_exact_actual_node_budget_blocks_before_decoder(self):
        import tempfile
        decode=json.loads
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bounded.json'
            for scalar in ('null','true','1','"x"','{}','[]'):
                for count in (17,18,19):
                    with self.subTest(scalar=scalar,count=count):
                        raw=('{"unknown":['+','.join([scalar]*count)+']}').encode();p.write_bytes(raw)
                        # Root object + array + each array value/container.
                        with patch.object(nav,'MAX_ROWS',1),patch.object(nav.json,'loads',wraps=decode) as loads:
                            if count<=18:
                                out=nav.load_context(p);self.assertEqual(len(out['unknown']),count);self.assertEqual(loads.call_count,1)
                            else:
                                with self.assertRaisesRegex(nav.MetricError,'RESOURCE_TREE'):nav.load_context(p)
                                self.assertEqual(loads.call_count,0)
                        self.assertEqual(p.read_bytes(),raw)
            # Genuine current declared budget: ~4 MiB, not a decoder/memory failure.
            raw=b'{"unknown":['+b'0,'*(nav.MAX_ROWS*20-2)+b'0]}';p.write_bytes(raw)
            with patch.object(nav.json,'loads',wraps=decode) as loads:
                with self.assertRaisesRegex(nav.MetricError,'RESOURCE_TREE'):nav.load_context(p)
                self.assertEqual(loads.call_count,0)
            self.assertEqual(p.read_bytes(),raw)

    def test_predecode_keys_escapes_literals_and_mixed_nodes_match_encoded(self):
        import tempfile
        shapes=[{f'key{i}':None for i in range(19)},
                {'escaped"\\,:[]{}':'a"\\,:[]{}','n':-1.25e-10,'bool':True,'null':None},
                {'nested':[{},[],{'key':[1,'x',False,None]}]},
                {'keys':[{'"[,':1},{'other':2}],'empty':{}}]
        decode=json.loads
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bounded.json'
            for value in shapes:
                with self.subTest(value=value):
                    raw=json.dumps(value,indent=2,ensure_ascii=False).encode();p.write_bytes(raw)
                    with patch.object(nav,'MAX_ROWS',1):
                        canonical=nav.encoded(value)
                        with patch.object(nav.json,'loads',wraps=decode) as loads:
                            loaded=nav.load_context(p);self.assertEqual(loads.call_count,1)
                        self.assertEqual(nav.encoded(loaded),canonical)
                    self.assertEqual(p.read_bytes(),raw)

    def test_predecode_invalid_JSON_depth_duplicate_and_nonfinite_remain_bounded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'bounded.json'
            for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}',b'{"a":1 2}',
                        b'{"a":"bad\\q"}',b'{"a":[',b'}',b'{"a":'+b'['*16+b'0'+b']'*16+b'}'):
                with self.subTest(raw=raw):
                    p.write_bytes(raw)
                    with self.assertRaises(nav.MetricError):nav.load_context(p)
                    self.assertEqual(p.read_bytes(),raw)
            p.write_bytes(nav.encoded(context(rows())))
            self.assertEqual(nav.calculate(rows(),nav.load_context(p))['status'],nav.COMPLETE)

if __name__ == "__main__":
    unittest.main(verbosity=2)


"""Synthetic workbook regressions, not supplier originals or trained forecasts."""
import gzip
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_rtdsm_sources as v, a4_macro_learning as learning, a4_data_center as center
from tools.macro_history_sources import digest,encoded


def workbook(alias='PCPI',labels=('PCPI18M1','PCPI18M2'),*,values=None,formula=False,external=False,extra=None):
    values=values or [('2017:11',[100,110]),('2017:12',[101,112]),('2018:01',[None,113])]
    strings=['DATE',*labels,*[r[0] for r in values],'#N/A']
    q=lambda s:'{'+v.MAIN+'}'+s
    sheet=ET.Element(q('worksheet'));data=ET.SubElement(sheet,q('sheetData'))
    first=ET.SubElement(data,q('row'),r='1')
    def col(i):
        text=''
        while i:i,n=divmod(i-1,26);text=chr(65+n)+text
        return text
    for i in range(len(labels)+1):
        c=ET.SubElement(first,q('c'),r=col(i+1)+'1',t='s');ET.SubElement(c,q('v')).text=str(i)
    for n,(observed,items) in enumerate(values,2):
        row=ET.SubElement(data,q('row'),r=str(n));c=ET.SubElement(row,q('c'),r='A'+str(n),t='s')
        ET.SubElement(c,q('v')).text=str(strings.index(observed))
        for i,value in enumerate(items,2):
            c=ET.SubElement(row,q('c'),r=col(i)+str(n),**({'t':'s'} if value is None else {}))
            if formula and n==2 and i==2:ET.SubElement(c,q('f')).text='1+1'
            ET.SubElement(c,q('v')).text=str(strings.index('#N/A')) if value is None else str(value)
    ss=ET.Element(q('sst'))
    for s in strings:ET.SubElement(ET.SubElement(ss,q('si')),q('t')).text=s
    book=ET.Element(q('workbook'));sheets=ET.SubElement(book,q('sheets'))
    ET.SubElement(sheets,q('sheet'),name=alias.lower(),sheetId='1',
        **{'{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id':'rId1'})
    rel=ET.Element('{'+v.RELS+'}Relationships')
    ET.SubElement(rel,'{'+v.RELS+'}Relationship',Id='rId1',Target='worksheets/sheet1.xml',
        **({'TargetMode':'External'} if external else {}))
    files={'xl/workbook.xml':ET.tostring(book),'xl/_rels/workbook.xml.rels':ET.tostring(rel),
        'xl/sharedStrings.xml':ET.tostring(ss),'xl/worksheets/sheet1.xml':ET.tostring(sheet)}
    files.update(extra or {})
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,raw in files.items():z.writestr(name,raw)
    return out.getvalue()


class RtdsmTests(unittest.TestCase):
    def setUp(self):
        self.docs=b'SYNTHETIC method documentation; not a supplier original'
        self.rights=b'SYNTHETIC rights fixture; not a permission grant'
        specs={k:(*s[:4],digest(self.docs)) for k,s in v.FEEDS.items()}
        self.register=patch.dict(v.FEEDS,specs);self.register.start();self.addCleanup(self.register.stop)

    def normalize(self,raw=None,feed='rtdsm_pcpi',**kwargs):
        return v.normalize(raw or workbook(),feed,collected_at='2018-03-02T00:00:00Z',**kwargs)

    def store(self,root,raw=None,collected='2018-03-02T00:00:00Z'):
        return v.store_capture(root,raw or workbook(),'rtdsm_pcpi',collected_at=collected,
            documentation_raw=self.docs,rights_raw=self.rights)

    def test_month_boundary_is_conservative_and_not_a_release_timestamp(self):
        rows,meta=self.normalize()
        self.assertEqual((meta['observations'],meta['vintages']),(5,2))
        self.assertTrue(all(r['published_at'] is None and not r['historical_pit_certified'] for r in rows))
        self.assertEqual(rows[0]['available_at'],'2018-02-01T00:00:00-05:00')
        self.assertIsNone(rows[0]['documented_vintage_date'])
        self.assertEqual(rows[0]['vintage_reference_month'],'2018-01-01')
        self.assertEqual(meta['historical_use'],'DATE_ARCHIVE_RESEARCH_ONLY')

    def test_quarter_vintage_keeps_monthly_observations_and_day_bound(self):
        raw=workbook('RUC',('RUC18Q1',),values=[('2017:12',[4.1]),('2018:01',[4.0])])
        rows,_=self.normalize(raw,'rtdsm_ruc')
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['frequency']=='monthly' and r['vintage_frequency']=='quarterly' for r in rows))
        self.assertEqual(rows[0]['documented_vintage_date'],'2018-02-15')
        self.assertEqual(rows[0]['available_at'],'2018-02-16T00:00:00-05:00')

    def test_dst_and_year_rollover_bounds(self):
        self.assertEqual(v.vintage_boundary('PCPI26M10','PCPI')[2],'2026-11-01T00:00:00-04:00')
        self.assertEqual(v.vintage_boundary('PCPI26M12','PCPI')[2],'2027-01-01T00:00:00-05:00')
        self.assertEqual(v.vintage_boundary('RUC26Q4','RUC')[2],'2026-11-16T00:00:00-05:00')

    def test_unfinished_vintage_month_is_excluded(self):
        rows,_=v.normalize(workbook(),'rtdsm_pcpi',collected_at='2018-02-15T12:00:00Z')
        self.assertEqual({r['vintage_label'] for r in rows},{'PCPI18M1'})

    def test_no_early_use_and_no_newer_vintage_filling(self):
        rows,_=self.normalize()
        self.assertEqual(v.asof_rows(rows,'2018-02-01T04:59:59Z'),[])
        old=v.asof_rows(rows,'2018-02-01T05:00:00Z')
        self.assertEqual([r['value'] for r in old],[100,101])
        self.assertEqual([r['value'] for r in v.asof_rows(rows,'2018-03-01T05:00:00Z')],[110,112,113])

    def test_missing_latest_cell_is_not_replaced_by_an_older_vintage(self):
        raw=workbook(values=[('2017:11',[100,110]),('2017:12',[101,112]),('2018:01',[None,None])])
        rows,_=self.normalize(raw)
        latest=v.asof_rows(rows,'2018-03-01T05:00:00Z')[-1]
        self.assertIsNone(latest['value']);self.assertEqual(latest['native_value_status'],'MISSING')

    def test_formula_external_link_and_unexpected_zip_member_refuse(self):
        for raw in [workbook(formula=True),workbook(external=True),workbook(extra={'../outside.xml':b'x'})]:
            with self.subTest(),self.assertRaises(ValueError):self.normalize(raw)

    def test_wrong_worksheet_root_and_dtd_refuse(self):
        with zipfile.ZipFile(io.BytesIO(workbook())) as archive:
            root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        root.tag='wrong-root'
        for raw_xml in [ET.tostring(root),b'<!DOCTYPE worksheet [<!ENTITY x "bad">]><worksheet/>']:
            with self.subTest(),self.assertRaises(ValueError):
                self.normalize(workbook(extra={'xl/worksheets/sheet1.xml':raw_xml}))

    def test_duplicate_or_wrong_frequency_vintages_refuse(self):
        for labels in [('PCPI18M1','PCPI18M1'),('PCPI18M2','PCPI18M1'),('PCPI18Q1','PCPI18M2')]:
            with self.subTest(labels=labels),self.assertRaises(ValueError):self.normalize(workbook(labels=labels))

    def test_missing_reference_row_and_observation_gap_refuse(self):
        for values in [[('2017:11',[100,110])],[('2017:11',[100,110]),('2018:01',[101,112])]]:
            with self.subTest(),self.assertRaises(ValueError):self.normalize(workbook(values=values))

    def test_current_units_and_release_features_are_not_daily_duplicates(self):
        rows,_=self.normalize();days=learning.mcal.get_calendar('NYSE').schedule('2018-01-02','2018-03-29')
        sessions=[dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in days.market_close.items()]
        features=learning.replay_features(rows,sessions)['change_1_month:cpi']
        self.assertEqual(features.notna().sum(),2)
        self.assertAlmostEqual(features.dropna().iloc[0],1.)
        self.assertEqual({r['unit'] for r in rows},{'index'})
        self.assertTrue(features.loc[:'2018-01-31'].isna().all())

    def test_future_revisions_and_columns_cannot_change_prior_features(self):
        base=workbook(labels=('PCPI18M1',),values=[('2017:11',[100]),('2017:12',[101]),('2018:01',[None])])
        old,_=self.normalize(base);new,_=self.normalize()
        days=learning.mcal.get_calendar('NYSE').schedule('2018-01-02','2018-02-28')
        sessions=[dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in days.market_close.items()]
        a=learning.replay_features(old,sessions);b=learning.replay_features(new,sessions)
        for key in a:pd.testing.assert_series_equal(a[key],b[key])

    def test_quarterly_archive_creates_one_release_sample(self):
        raw=workbook('RUC',('RUC18Q1',),values=[('2017:12',[4.1]),('2018:01',[4.0])])
        rows,_=self.normalize(raw,'rtdsm_ruc');days=learning.mcal.get_calendar('NYSE').schedule('2018-01-02','2018-03-29')
        sessions=[dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in days.market_close.items()]
        series=learning.replay_features(rows,sessions)['change_1_month:unemployment']
        self.assertEqual(series.notna().sum(),1)

    def test_original_and_normalized_pair_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=self.store(tmp);b=self.store(tmp)
            self.assertEqual(a,b)
            rows,meta=v.read_generation(v.PreparedReader(tmp),a['generation_sha256'],cutoff='2018-03-30T00:00:00Z')
            self.assertEqual(len(rows),5);self.assertFalse(meta['training_admitted'])
            with self.assertRaisesRegex(ValueError,'RTDSM_FUTURE_CAPTURE'):
                v.read_generation(v.PreparedReader(tmp),a['generation_sha256'],cutoff='2018-03-01T00:00:00Z')

    def test_interruption_before_manifest_can_resume_without_overwriting_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=v.exclusive
            def interrupted(path,raw):
                if path.parent.name=='generations':raise OSError('synthetic interrupted publication')
                return original(path,raw)
            with patch.object(v,'exclusive',side_effect=interrupted),self.assertRaises(OSError):self.store(tmp)
            self.assertFalse((Path(tmp)/'generations').exists())
            existing={p.name:p.read_bytes() for p in (Path(tmp)/'objects').iterdir()}
            item=self.store(tmp)
            for sha,raw in existing.items():self.assertEqual((Path(tmp)/'objects'/sha).read_bytes(),raw)
            rows,_=v.read_generation(v.PreparedReader(tmp),item['generation_sha256'],cutoff='2018-03-30T00:00:00Z')
            self.assertEqual(len(rows),5)

    def test_original_tamper_and_document_mismatch_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            item=self.store(tmp);p=Path(tmp)/'objects'/item['manifest']['original_sha256'];p.write_bytes(b'tampered')
            with self.assertRaises(ValueError):v.read_generation(v.PreparedReader(tmp),item['generation_sha256'],cutoff='2018-03-30T00:00:00Z')
        with tempfile.TemporaryDirectory() as tmp,self.assertRaisesRegex(ValueError,'RTDSM_DOCUMENTATION_PIN'):
            v.store_capture(tmp,workbook(),'rtdsm_pcpi',collected_at='2018-03-02T00:00:00Z',documentation_raw=b'wrong',rights_raw=self.rights)

    def test_forged_normalized_member_cannot_override_original_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            item=self.store(tmp);meta=item['manifest'];rows,_=self.normalize();rows[0]['value']=999
            raw=gzip.compress(b''.join(v.p._normalized_lines(rows)),mtime=0)
            forged=dict(meta,normalized_object_sha256=digest(raw),normalized_bytes=len(raw))
            sha=digest(encoded(forged));(Path(tmp)/'objects'/digest(raw)).write_bytes(raw)
            (Path(tmp)/'generations'/(sha+'.json')).write_bytes(encoded(forged))
            with self.assertRaisesRegex(ValueError,'RTDSM_NORMALIZATION_REPLAY'):
                v.read_generation(v.PreparedReader(tmp),sha,cutoff='2018-03-30T00:00:00Z')

    def learning_fixture(self,tmp):
        item=self.store(tmp);rows,_=self.normalize();days=learning.mcal.get_calendar('NYSE').schedule('2018-01-02','2018-03-29')
        payload=dict(schema='a4-macro-learning-inputs-v1',cutoff='2018-03-29T22:00:00Z',prices={},observations=rows,
            sessions=[dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in days.market_close.items()])
        meta=item['manifest'];sha=meta['original_sha256']
        policy=dict(schema='a4-learning-input-policy-v1',purpose='MACRO_RELATIONSHIP_RESEARCH',
            available_at='2018-01-01T00:00:00Z',expires_at='2018-04-01T00:00:00Z',input_pins=[digest(encoded(payload))],
            reviewed_rights_pins=['a'*64,digest(self.rights)],reviewed_source_receipt_pins=[item['generation_sha256']],
            source_bindings={sha:dict(size_bytes=meta['original_bytes'],source_ids=['rtdsm:PCPI'],
                purpose='MACRO_RELATIONSHIP_RESEARCH',historical_use='DATE_ARCHIVE_RESEARCH_ONLY',
                rights_evidence_sha256='a'*64,source_receipt_sha256=item['generation_sha256'],
                vintage_manifest_sha256=item['generation_sha256'])})
        def resolve(sha):
            files=[Path(tmp)/'objects'/sha,Path(tmp)/'generations'/(sha+'.json')]
            return next(f for f in files if f.is_file()).read_bytes()
        return payload,policy,resolve

    def test_macro_only_input_can_validate_without_price_admission_or_fitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload,policy,resolve=self.learning_fixture(tmp)
            with patch.object(learning,'fit_trial',side_effect=AssertionError('no fit allowed')):
                self.assertEqual(len(learning.validate_inputs(payload,policy,digest(encoded(policy)),resolve)),len(payload['sessions']))
            self.assertEqual(payload['prices'],{})

    def test_policy_pin_cannot_authorize_edited_early_vintage_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload,policy,resolve=self.learning_fixture(tmp)
            payload['observations'][0]['available_at']='2018-01-10T00:00:00Z';policy['input_pins']=[digest(encoded(payload))]
            with self.assertRaisesRegex(ValueError,'A4_LEARNING_VINTAGE_ROW_REPLAY'):
                learning.validate_inputs(payload,policy,digest(encoded(policy)),resolve)

    def test_forward_only_or_missing_notice_review_cannot_admit_vintage_history(self):
        for change in ('forward','rights','receipt'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                payload,policy,resolve=self.learning_fixture(tmp);binding=next(iter(policy['source_bindings'].values()))
                if change=='forward':binding['historical_use']='FORWARD_CAPTURE_ONLY'
                elif change=='rights':policy['reviewed_rights_pins']=['a'*64]
                else:binding['vintage_manifest_sha256']='c'*64
                with self.assertRaises(ValueError):learning.validate_inputs(payload,policy,digest(encoded(policy)),resolve)

    def test_data_center_reuses_reader_and_keeps_vintages_out_of_current_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            item=self.store(tmp)
            context,audit,n=center.vintage_context([dict(root=tmp,generation_sha256=item['generation_sha256'])],
                '2018-03-30T00:00:00Z',budget={'bytes':0})
            self.assertEqual(n,5);self.assertEqual(audit,[])
            self.assertEqual(context[0]['latest']['value'],113)
            self.assertFalse(context[0]['training_admitted']);self.assertFalse(context[0]['original_pairs_remote_verified'])

    def test_future_capture_is_audit_only_not_a_past_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            item=self.store(tmp)
            context,audit,n=center.vintage_context([dict(root=tmp,generation_sha256=item['generation_sha256'])],
                '2018-03-01T00:00:00Z',budget={'bytes':0})
            self.assertEqual((context,n),([],0));self.assertEqual(len(audit),1)

    def test_later_reissued_original_does_not_change_an_earlier_catalog_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=self.store(tmp)
            raw=workbook(values=[('2017:11',[900,910]),('2017:12',[901,912]),('2018:01',[None,913])])
            new=self.store(tmp,raw=raw,collected='2018-03-03T00:00:00Z')
            refs=[dict(root=tmp,generation_sha256=x['generation_sha256']) for x in (old,new)]
            a,_,n=center.vintage_context(refs[:1],'2018-03-02T12:00:00Z',budget={'bytes':0})
            b,audit,m=center.vintage_context(refs,'2018-03-02T12:00:00Z',budget={'bytes':0})
            self.assertEqual(a,b);self.assertEqual(n,m);self.assertEqual(len(audit),1)

    def test_newest_broken_capture_never_falls_back_to_old_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=self.store(tmp);new=self.store(tmp,collected='2018-03-03T00:00:00Z')
            path=Path(tmp)/'objects'/new['manifest']['normalized_object_sha256'];path.write_bytes(b'broken')
            with self.assertRaises(ValueError):center.vintage_context([
                dict(root=tmp,generation_sha256=x['generation_sha256']) for x in (old,new)],
                '2018-03-30T00:00:00Z',budget={'bytes':0})

    def test_long_horizon_preparation_preserves_the_declared_learning_family(self):
        self.assertEqual(learning.prospective_horizon_capacity(2639)['dense_mature_nonoverlap_window_upper_bound'],5)
        cap=learning.prospective_horizon_capacity(10000)
        self.assertEqual(cap['dense_mature_nonoverlap_window_upper_bound'],19)
        self.assertEqual(cap['minimum_sessions_before_oos_training'],10101)
        self.assertFalse(cap['registered_learning_horizon']);self.assertFalse(cap['sufficient_even_before_oos'])
        self.assertEqual(learning.analysis.HORIZONS,(1,5,10,21,63,126,252))
        for n in (-1,10001,True):
            with self.assertRaises(ValueError):learning.prospective_horizon_capacity(n)

    def test_dated_vintage_challenger_cannot_use_an_unaligned_current_report_clock(self):
        from tests.a4_macro_learning_smoke import synthetic_direction_release
        report,trial,policy=synthetic_direction_release()
        trial['dated_vintage_sources']=['rtdsm:PCPI']
        trial['trial_sha256']=digest(encoded({k:v for k,v in trial.items() if k!='trial_sha256'}))
        policy['reviewed_trial_pins']=[trial['trial_sha256']]
        before=encoded(report)
        with self.assertRaisesRegex(ValueError,'A4_DATED_VINTAGE_FORECAST_CLOCK_ALIGNMENT_REQUIRED'):
            learning.forecast_release(report,trial,policy,digest(encoded(policy)))
        self.assertEqual(before,encoded(report))

    def dated_release_fixture(self,tmp,*,changed_prefix=False,session='2018-04-02',cutoff='2018-04-02T22:00:00Z'):
        from tests.a4_macro_learning_smoke import synthetic_direction_release
        old=self.store(tmp);old_rows,_=v.read_generation(v.PreparedReader(tmp),old['generation_sha256'],cutoff='2018-03-02T22:00:00Z')
        days=learning.mcal.get_calendar('NYSE').schedule('2018-01-02','2018-03-02')
        old_sessions=[dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in days.market_close.items()]
        report,trial,release=synthetic_direction_release()
        trial.update(cutoff='2018-03-02T22:00:00Z',dated_vintage_sources=['rtdsm:PCPI'],logical_sources={'cpi':'rtdsm:PCPI'},
            feature_history=learning.feature_history(learning.replay_features(old_rows,old_sessions),old_sessions))
        for row in trial['results']:
            row.update(status='INSUFFICIENT_EVIDENCE',frozen_model=None)
            if row['target'] in ('SPY','QQQ') and row['horizon_sessions']==1 and row['outcome']=='return' and row['feature']=='change_1_month:cpi':
                row.update(status='SHADOW_CANDIDATE',frozen_model=dict(mean=0.,sd=1.,intercept=0.,
                    coefficient=.01 if row['target']=='SPY' else -.01))
        trial['trial_sha256']=digest(encoded({k:x for k,x in trial.items() if k!='trial_sha256'}))
        raw=workbook(labels=('PCPI18M1','PCPI18M2','PCPI18M3'),values=[
            ('2017:11',[99 if changed_prefix else 100,110,115]),('2017:12',[101,112,116]),
            ('2018:01',[None,113,118]),('2018:02',[None,None,120])])
        new=self.store(tmp,raw=raw,collected='2018-04-02T00:00:00Z');rows,meta=v.read_generation(v.PreparedReader(tmp),new['generation_sha256'],cutoff=cutoff)
        days=learning.mcal.get_calendar('NYSE').schedule('2018-01-02',session)
        payload=dict(schema='a4-macro-learning-inputs-v1',cutoff=cutoff,prices={},observations=rows,
            sessions=[dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in days.market_close.items()])
        sha=meta['original_sha256']
        policy=dict(schema='a4-learning-input-policy-v1',purpose='MACRO_RELATIONSHIP_RESEARCH',
            available_at='2018-04-02T01:00:00Z',expires_at='2018-04-05T00:00:00Z',input_pins=[digest(encoded(payload))],
            reviewed_rights_pins=['a'*64,digest(self.rights)],reviewed_source_receipt_pins=[new['generation_sha256']],
            source_bindings={sha:dict(size_bytes=meta['original_bytes'],source_ids=['rtdsm:PCPI'],
                purpose='MACRO_RELATIONSHIP_RESEARCH',historical_use='DATE_ARCHIVE_RESEARCH_ONLY',
                rights_evidence_sha256='a'*64,source_receipt_sha256=new['generation_sha256'],
                vintage_manifest_sha256=new['generation_sha256'])})
        release.update(available_at='2018-03-03T00:00:00Z',expires_at='2018-04-05T00:00:00Z',
            reviewed_trial_pins=[trial['trial_sha256']],forward_input_pins=[digest(encoded(payload))],
            forward_input_policy_pins=[digest(encoded(policy))])
        report.update(session=session,cutoff=cutoff)
        # Poison a current-source change: dated models must never consume it.
        report['macro_direction_inputs']={'cpi':dict(frequency='monthly',status='OBSERVED',changes={'1':{'value':999}})}
        def resolve(sha):
            return next(f for f in (Path(tmp)/'objects'/sha,Path(tmp)/'generations'/(sha+'.json')) if f.is_file()).read_bytes()
        options=dict(forward_inputs=payload,forward_policy=policy,forward_policy_sha256=digest(encoded(policy)),artifact_resolver=resolve)
        return report,trial,release,options

    def test_dated_forward_uses_replayed_event_and_not_current_bls_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,trial,policy,options=self.dated_release_fixture(tmp)
            forecasts=learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options)
            self.assertEqual({r['target']:r['estimate'] for r in forecasts},{'SPY':.02,'QQQ':-.02})
            proof=report['learning_provenance']['forward_context']
            self.assertEqual(proof['feature_anchor_close_utc'],'2018-04-02T20:00:00+00:00')
            self.assertTrue(proof['training_prefix_verified']);self.assertTrue(proof['originals_replayed'])
            self.assertFalse(report['portfolio_overlay_allowed'])

    def test_dated_forward_does_not_repeat_a_monthly_release_on_next_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,trial,policy,options=self.dated_release_fixture(tmp,session='2018-04-03',cutoff='2018-04-03T22:00:00Z')
            self.assertEqual(learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options),[])
            self.assertTrue(all(r['direction']=='INSUFFICIENT_EVIDENCE' for r in report['benchmark_outlook']))

    def test_postclose_weekend_vintage_cannot_enter_previous_close_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,trial,policy,options=self.dated_release_fixture(tmp,session='2018-03-29',cutoff='2018-04-02T12:00:00Z')
            self.assertEqual(learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options),[])

    def test_reissued_archive_cannot_change_the_training_feature_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,trial,policy,options=self.dated_release_fixture(tmp,changed_prefix=True);before=encoded(report)
            with self.assertRaisesRegex(ValueError,'A4_FORWARD_TRAINING_PREFIX_CHANGED'):
                learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options)
            self.assertEqual(before,encoded(report))

    def test_forward_row_omission_or_duplication_is_rejected_even_with_new_pins(self):
        for duplicate in (True,False):
            with self.subTest(duplicate=duplicate),tempfile.TemporaryDirectory() as tmp:
                report,trial,policy,options=self.dated_release_fixture(tmp);payload=options['forward_inputs']
                if duplicate:payload['observations'].append(copy.deepcopy(payload['observations'][0]))
                else:payload['observations'].pop()
                options['forward_policy']['input_pins']=[digest(encoded(payload))]
                options['forward_policy_sha256']=digest(encoded(options['forward_policy']))
                policy.update(forward_input_pins=[digest(encoded(payload))],forward_input_policy_pins=[options['forward_policy_sha256']])
                with self.assertRaisesRegex(ValueError,'A4_FORWARD_COMPLETE_VINTAGE_ROWS_REQUIRED'):
                    learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options)

    def test_dated_forward_policy_expiry_review_and_original_tamper_fail_closed(self):
        for case in ('review','expiry','original','future','source'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as tmp:
                report,trial,policy,options=self.dated_release_fixture(tmp);before=encoded(report)
                if case=='review':policy['forward_input_policy_pins']=[]
                elif case=='expiry':options['forward_policy']['expires_at']=report['cutoff']
                elif case=='original':options['artifact_resolver']=lambda _:b'tampered'
                elif case=='future':options['forward_inputs']['cutoff']='2018-04-03T22:00:00Z'
                else:options['forward_inputs']['observations'][0]['source_id']='bls:CUUR0000SA0'
                with self.assertRaises(ValueError):learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options)
                self.assertEqual(before,encoded(report))

    def test_native_request_replays_the_same_dated_forecast_with_originals(self):
        from tools import market_analysis_engine as market
        with tempfile.TemporaryDirectory() as tmp:
            report,trial,policy,options=self.dated_release_fixture(tmp)
            payload=options['forward_inputs'];input_policy=options['forward_policy'];bodies={};entries=[]
            for path in sorted(Path(tmp).glob('*/*')):
                body=path.read_bytes();name='originals/'+digest(body);bodies[name]=body
                if any(s['sha256']==digest(body) for s in entries):continue
                entries.append(dict(kind='learning_original',path=name,sha256=digest(body),status='COLLECTED',collected_at='2018-04-02T01:00:00Z'))
            bodies['release.json']=encoded(dict(trial=trial,policy=policy,forward_inputs=payload,forward_policy=input_policy))
            entries.append(dict(kind='learning_release',path='release.json',sha256=digest(bodies['release.json']),
                policy_sha256=digest(encoded(policy)),forward_policy_sha256=options['forward_policy_sha256'],status='COLLECTED',collected_at=report['cutoff']))
            request=dict(schema=market.REQUEST_SCHEMA_V2,market='US',session=report['session'],available_at=report['cutoff'],
                expires_at='2018-04-03T12:00:00Z',inputs=entries);raw=encoded(request)
            actual=market.analyze(raw,bodies,expected_sha=digest(raw),cutoff=report['cutoff'],session=report['session'])
            direct=learning.forecast_release(report,trial,policy,digest(encoded(policy)),**options)
            self.assertEqual(actual['historical_evidence']['predictions'],direct)
            self.assertEqual(actual['status'],'DATA_BLOCKED');self.assertEqual(actual['market_assessment']['ready_axis_count'],0)
            self.assertFalse(actual['source_and_pit_admission'])

    def test_cloud_forward_request_requires_the_exact_external_request_pin(self):
        from tools import run_a4_research_cycle as cycle
        with tempfile.TemporaryDirectory() as tmp:
            report,trial,policy,options=self.dated_release_fixture(tmp);root=Path(tmp)/'bundle';root.mkdir()
            payload=encoded(options['forward_inputs']);input_policy=encoded(options['forward_policy'])
            (root/'inputs.json').write_bytes(payload);(root/'policy.json').write_bytes(input_policy)
            request=encoded(dict(schema='a4-learning-request-v1',inputs=dict(path='inputs.json',sha256=digest(payload)),
                policy=dict(path='policy.json',sha256=digest(input_policy)),originals={}))
            (root/'forward_request.json').write_bytes(request)
            with self.assertRaisesRegex(ValueError,'FORWARD_REQUEST_NOT_REVIEWED'):cycle.load_forward_context(root,policy)
            policy['forward_request_sha256']=digest(request)
            loaded=cycle.load_forward_context(root,policy)
            self.assertEqual(loaded['forward_inputs'],options['forward_inputs'])
            (root/'forward_request.json').write_bytes(request+b' ')
            with self.assertRaisesRegex(ValueError,'FORWARD_REQUEST_NOT_REVIEWED'):cycle.load_forward_context(root,policy)


if __name__=='__main__':unittest.main()

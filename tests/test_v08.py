"""Descriptive arithmetic, frozen reporting and refresh/retention contracts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_bout_context import aggregate,normalize_bout,validate_context,form_rows,capture,FightSource
from analyzer_refresh import refresh_request
from analyzer_history import History,utc_now

def meta(identifier='f',date='2020-01-01'):
    return dict(fight_id=identifier,event_date=date,opponent_id='b',opponent='Beta',result='win',method='Decision')

def bout(identifier='f',landed=10,attempted=20,duration=60,opponent=5):
    own=dict(fighter_id='a',significant_strikes_landed=str(landed),significant_strikes_attempted=str(attempted),
        takedowns_landed='0',takedowns_attempted='0',elapsed_seconds=str(duration),control_time_seconds='0')
    other=dict(fighter_id='b',significant_strikes_landed=str(opponent),significant_strikes_attempted='10',
        takedowns_landed='0',takedowns_attempted='0',elapsed_seconds=str(duration),control_time_seconds='0')
    return normalize_bout(meta(identifier),[own,other],'men','a')

class Arithmetic(unittest.TestCase):
    def test_pooled_ratios_and_time_not_average_percentages(self):
        data=aggregate([bout(landed=10,attempted=10,duration=60),bout('g',landed=0,attempted=90,duration=180)])
        rows={v['id']:v for v in data['metrics']}
        self.assertAlmostEqual(rows['sig_accuracy']['value'],.1)
        self.assertAlmostEqual(rows['sig_per_min']['value'],2.5)
        self.assertAlmostEqual(rows['absorbed_per_min']['value'],2.5)
        self.assertEqual(rows['td_accuracy']['value'],None)
        self.assertEqual(rows['control_share']['value'],0)
        self.assertEqual(rows['sig_accuracy']['denominator'],100)
    def test_missing_attempts_do_not_drop_valid_time_metric(self):
        value=bout();value['stats']['sig_attempted']=None
        rows={v['id']:v for v in aggregate([value])['metrics']}
        self.assertEqual(rows['sig_accuracy']['missing_bouts'],1)
        self.assertEqual(rows['sig_per_min']['value'],10)
    def test_invalid_landed_counts_and_duration_do_not_become_zero(self):
        value=bout(landed=30,attempted=20,duration=0)
        self.assertIsNone(value['stats']['sig_landed']);self.assertIsNone(value['duration_seconds'])
        self.assertTrue(all(r['value'] is None or r['id']=='control_share' for r in aggregate([value])['metrics']))
    def test_duplicate_or_missing_identity_withholds_opponent(self):
        own=dict(fighter_id='a',elapsed_seconds='60',significant_strikes_landed='2',significant_strikes_attempted='3')
        value=normalize_bout(meta(),[own,dict(fighter_id='b'),dict(fighter_id='b')],'men','a')
        self.assertFalse(value['paired']);self.assertIsNone(value['opponent_stats']['sig_landed'])
    def test_womens_repaired_fields_are_authoritative(self):
        own=dict(profile_url='https://example/a',elapsed_seconds='60',sig_str_landed_repaired='',sig_str_landed_total='99')
        value=normalize_bout(meta(),[own],'women','a')
        self.assertIsNone(value['stats']['sig_landed'])

class HistoryAndRefresh(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.history=History(self.root)
        self.request=dict(operation='compare',sex='men',fighter_a='Alpha',fighter_b='Beta',fighter_a_id='a',fighter_b_id='b',division='Lightweight',fight_date='2020-01-02',workers='automatic')
        self.payload=dict(fighter_a='Alpha',fighter_b='Beta',fighter_a_id='a',fighter_b_id='b',fight_date='2020-01-02',result_state='comparison',generated_at=utc_now(),calculation_request=self.request)
    def tearDown(self):self.temp.cleanup()
    def test_refresh_preserves_date_mode_and_uses_compute_cache(self):
        original=copy.deepcopy(self.request);entry=dict(id='1'*32,request=self.request)
        request=refresh_request(entry)
        self.assertEqual(request['fight_date'],'2020-01-02');self.assertEqual(request['operation'],'compare')
        self.assertTrue(request['skip_saved_result']);self.assertTrue(request['use_cache'])
        self.assertNotIn('force_recalculate',request);self.assertEqual(self.request,original)
        self.assertNotEqual(refresh_request(entry,True)['fight_date'],'2020-01-02')
    def test_refresh_rejects_legacy_identity_and_manual_profile(self):
        for update in (dict(fighter_a_id=''),dict(profiles_sha256='x')):
            with self.assertRaises(ValueError):refresh_request(dict(request={**self.request,**update}))
    def test_refresh_does_not_replace_matching_original(self):
        first=self.history.save(self.request,{},self.payload)
        second=self.history.save(self.request,{},dict(self.payload,generated_at=utc_now()),preserve_id=first)
        self.assertNotEqual(first,second);self.assertEqual(len(self.history.entries()),2)
        self.assertEqual(self.history.load(first)['payload'],self.payload)
    def test_pruning_keeps_original_at_capacity(self):
        first=self.history.save(self.request,{},self.payload)
        with mock.patch('analyzer_history.MAX_ENTRIES',2):
            self.history.save({**self.request,'workers':2},{},self.payload)
            newest=self.history.save(self.request,{},self.payload,preserve_id=first)
        self.assertEqual({e['id'] for e in self.history.entries()},{first,newest})
    def test_index_is_rebuilt_on_corruption_and_checks_current_bytes(self):
        first=self.history.save(self.request,{},self.payload)
        self.assertEqual(self.history.summaries()[0]['id'],first)
        (self.root/'.runtime/history_index.json').write_text('{bad')
        self.assertEqual(self.history.summaries()[0]['id'],first)
        (self.root/'.runtime/history_index.json').write_text('[]')
        self.assertEqual(self.history.summaries()[0]['id'],first)
        path=self.history.directory/(first+'.json');text=path.read_text();path.write_text(text.replace('Alpha','Other'))
        self.assertEqual(self.history.summaries(),[])
    def test_full_history_does_not_delete_original_when_bytes_cannot_fit(self):
        first=self.history.save(self.request,{},self.payload)
        with mock.patch('analyzer_history.MAX_BYTES',1500):
            with self.assertRaises(ValueError):self.history.save(self.request,{},dict(self.payload,padding='x'*1000),preserve_id=first)
        self.assertTrue((self.history.directory/(first+'.json')).exists())

class SourceAndReports(unittest.TestCase):
    def test_structural_cache_still_hashes_same_size_same_timestamp_changes(self):
        import os
        import analyzer_support as support
        from test_safety import mini_root
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);mini_root(root)
            with mock.patch.object(support,'csv_info',wraps=support.csv_info) as scan:
                self.assertTrue(all(c['status']=='PASS' for c in support.data_health(root)))
                self.assertEqual(scan.call_count,1)
                self.assertTrue(all(c['status']=='PASS' for c in support.data_health(root)))
                self.assertEqual(scan.call_count,1)
            path=root/'mens_ufc_model/data/example.csv';stamp=path.stat()
            path.write_bytes(path.read_bytes().replace(b',1',b',2'));os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertTrue(any(c['status']=='FAIL' for c in support.data_health(root)))
    def test_corrupt_structural_cache_rescans(self):
        import analyzer_support as support
        from test_safety import mini_root
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);mini_root(root);support.data_health(root)
            for path in (root/'.runtime/validation_cache').glob('*.json'):path.write_text('{bad')
            with mock.patch.object(support,'csv_info',wraps=support.csv_info) as scan:
                self.assertTrue(all(c['status']=='PASS' for c in support.data_health(root)));self.assertEqual(scan.call_count,1)
    def test_source_change_during_capture_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rows.csv';path.write_text('x\n1\n')
            source=FightSource(folder,'men',{'fighter_a':('Alpha','a'),'fighter_b':('Beta','b')})
            source.records(path);path.write_text('x\n2\n')
            with self.assertRaises(ValueError):source.verify()
    def test_new_blocks_validation_rejects_future_and_invalid_support(self):
        b=bout();data=aggregate([b]);form=dict(schema=1,history_cutoff='2020-01-02',fighter_a=dict(fighter_id='a',windows={'3':data,'5':data,'career':data}),fighter_b=dict(fighter_id='b',windows={'3':data,'5':data,'career':data}))
        payload=dict(recent_form=form)
        validate_context(payload)
        changed=copy.deepcopy(payload);changed['recent_form']['fighter_a']['windows']['3']['metrics'][0]['missing_bouts']=5
        with self.assertRaises(ValueError):validate_context(changed)
        for block in ([],{'schema':1,'history_cutoff':'2020-01-02','fighter_a':[]}):
            with self.assertRaises(ValueError):validate_context({'bout_details':block})
    def test_compact_formats_frozen_fixtures_without_predictions_in_partial(self):
        from analyzer_compact_report import compact_html
        from test_usability import sample
        payload=sample();before=copy.deepcopy(payload)
        html=compact_html(payload,'3')
        self.assertIn('Last 3',html);self.assertIn('@media print',html);self.assertNotIn('<script',html)
        partial=dict(payload,result_state='cancelled',fighter_a='A < B')
        text=compact_html(partial)
        self.assertIn('A &lt; B',text);self.assertNotIn('class="prediction"',text)
        self.assertEqual(payload,before)

if __name__=='__main__':unittest.main()

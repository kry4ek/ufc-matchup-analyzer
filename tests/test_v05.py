"""Cross-request cache, reviewed corrections, frozen summaries and comparison safety."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from analyzer_cache import ComputeCache,clear_cache,cache_size
from analyzer_summary import build_summary,metric_records,format_summary
from analyzer_comparison import compare_entries,format_comparison,comparison_html
from analyzer_corrections import canonical,diff_capture,write_rows,read_rows,SOURCE_PATHS,apply_source,validate_preview,validate_pair
from analyzer_history import History,fingerprint
from analyzer_reporting import format_html
from analyzer_results import format_result
from test_gui import result

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.cache=ComputeCache(self.root,{'dataset':'abc','date':'2020-01-01'})
    def tearDown(self):self.temp.cleanup()
    def test_context_and_inputs_require_exact_compatibility(self):
        self.cache.save('features',{'division':'a'},[1,2])
        self.assertEqual(self.cache.load('features',{'division':'a'}),[1,2])
        self.assertIsNone(self.cache.load('features',{'division':'b'}))
        for field in ('dataset','date','code','dependencies'):
            context=dict(self.cache.context);context[field]='changed'
            self.assertIsNone(ComputeCache(self.root,context).load('features',{'division':'a'}))
    def test_loaded_mutable_context_is_independent(self):
        self.cache.save('dated',{}, {'cursor':0,'histories':[]})
        value=self.cache.load('dated',{});value['histories'].append('later');value['cursor']=10
        self.assertEqual(self.cache.load('dated',{})['cursor'],0)
        self.assertEqual(self.cache.load('dated',{})['histories'],[])
    def test_corrupt_artifact_falls_back_and_disabled_reads_recompute(self):
        self.cache.save('model',{}, {'score':1})
        path=next(self.cache.directory.glob('*.bin'));path.write_bytes(b'bad')
        self.assertIsNone(self.cache.load('model',{}))
        self.cache.save('model',{}, {'score':1})
        fresh=ComputeCache(self.root,self.cache.context,enabled=False)
        self.assertEqual(fresh.get('model',{},lambda:{'score':2}),{'score':2})
        self.assertEqual(self.cache.load('model',{}),{'score':2})
    def test_storage_failure_does_not_fail_calculation(self):
        with mock.patch('analyzer_cache.atomic_json',side_effect=OSError('disk')):
            self.assertEqual(self.cache.get('features',{},lambda:[3]),[3])
        self.assertIsNone(self.cache.load('features',{}))
    def test_low_disk_space_keeps_successful_result_without_artifact(self):
        with mock.patch('analyzer_cache.shutil.disk_usage',return_value=mock.Mock(free=1)):
            self.assertEqual(self.cache.get('features',{},lambda:[4]),[4])
        self.assertEqual(cache_size(self.root),0)
    def test_bounded_cache_and_clear_preserve_history(self):
        cache=ComputeCache(self.root,{},limit=800)
        for i in range(5):cache.save('x',{'i':i},'x'*250)
        self.assertLessEqual(sum(p.stat().st_size for p in cache.directory.glob('*.bin')),800)
        history=self.root/'.runtime/history/keep.json';history.parent.mkdir();history.write_text('{}')
        clear_cache(self.root);self.assertEqual(cache_size(self.root),0);self.assertTrue(history.exists())
    def test_interrupted_temporary_artifacts_are_removed(self):
        self.cache.directory.mkdir(parents=True);(self.cache.directory/'partial.tmp').write_bytes(b'x'*1000)
        (self.cache.directory/'orphan.json').write_text('{}')
        ComputeCache(self.root,{})
        self.assertEqual(cache_size(self.root),0)
    def test_moved_app_does_not_load_resources_with_old_absolute_paths(self):
        import shutil
        self.cache.save('resources',{}, {'training_path':str(self.root/'training.csv')})
        moved=self.root/'moved';shutil.copytree(self.root/'.runtime',moved/'.runtime')
        self.assertIsNone(ComputeCache(moved,self.cache.context).load('resources',{}))

def sample():
    p=result();p.update(fighter_a_id='a',fighter_b_id='b',generated_at='2026-01-01',result_state='complete',coverage={'a':{'fights':12},'b':{'fights':5}})
    p['fighter_a_comparison']=dict(ufc_fights_before=12,elo_before=1800,days_since_last_fight=300)
    p['fighter_b_comparison']=dict(ufc_fights_before=5,elo_before=1600,days_since_last_fight=90)
    p['metric_records']=metric_records(p);p['matchup_summary']=build_summary(p)
    p['fight_evidence']=dict(fighter_a=[dict(fight_id='f',content_fingerprint='x')],fighter_b=[])
    return p

def entry(p):return dict(payload=p,request=dict(sex='men',operation='predict'),context=dict(datasets={'raw':'x'},code={'engine':'x'}))

class SummaryComparisonTests(unittest.TestCase):
    def test_summary_uses_frozen_values_and_exports(self):
        p=sample();summary=format_summary(p)
        self.assertIn('12',summary);self.assertIn('5',summary)
        self.assertIn(summary,format_result(p))
        self.assertIn('Matchup summary',format_html(p))
        frozen=copy.deepcopy(p['matchup_summary']);p['fighter_a_comparison']['ufc_fights_before']=99
        self.assertEqual(p['matchup_summary'],frozen)
    def test_missing_and_sparse_support_cannot_force_claims(self):
        p=sample();p['fighter_a_comparison']={};p['fighter_b_comparison']={}
        self.assertIsNone(build_summary(p)['observations'][0]['metric_id'])
    def test_smoothed_rates_require_attempt_support_and_use_percent_units(self):
        p=sample();p['model_version']='v3_bayes_smoothed'
        for side,value in (('a',.7),('b',.4)):
            p['fighter_'+side+'_snapshot']={};p['fighter_'+side+'_comparison']={'v3_bayes_sig_str_acc_s20_women_style':value,'v3_bayes_sig_str_acc_denominator_before':30}
        summary=build_summary(p)
        self.assertIn('70.0%',summary['observations'][0]['text'])
        p['fighter_a_comparison']['v3_bayes_sig_str_acc_denominator_before']=0
        summary=build_summary(p)
        self.assertIsNone(summary['observations'][0]['metric_id']);self.assertTrue(summary['limitations'])
        p=sample();p['coverage']={'a':{'fights':0},'b':{'fights':0}}
        p['fighter_a_comparison'].pop('ufc_fights_before');p['fighter_b_comparison'].pop('ufc_fights_before')
        p['fighter_a_comparison'].pop('days_since_last_fight');p['fighter_b_comparison'].pop('days_since_last_fight')
        self.assertIsNone(build_summary(p)['observations'][0]['metric_id'])
    def test_reversed_fighters_are_aligned_by_identity(self):
        a=sample();b=copy.deepcopy(a)
        for suffix in ('','_id','_win_probability','_comparison'):
            b['fighter_a'+suffix],b['fighter_b'+suffix]=b['fighter_b'+suffix],b['fighter_a'+suffix]
        b['metric_records']=metric_records(b)
        b['fight_evidence']['fighter_a'],b['fight_evidence']['fighter_b']=b['fight_evidence']['fighter_b'],b['fight_evidence']['fighter_a']
        compared=compare_entries(entry(a),entry(b))
        self.assertTrue(compared['reversed_sides']);self.assertEqual(compared['metrics'],[])
        self.assertEqual(compared['probability'][0]['delta_pp'],0)
    def test_ambiguous_identity_and_different_family_rejected(self):
        a=entry(sample());b=copy.deepcopy(a);b['payload']['fighter_b_id']=''
        with self.assertRaises(ValueError):compare_entries(a,b)
        b=copy.deepcopy(a);b['request']['sex']='women'
        with self.assertRaises(ValueError):compare_entries(a,b)
    def test_changed_context_and_probability_are_not_causal_claims(self):
        a=entry(sample());b=copy.deepcopy(a);b['payload']['fighter_a_win_probability']=.6;b['context']['datasets']['raw']='new'
        comparison=compare_entries(a,b)
        self.assertTrue(comparison['context_changes']);self.assertTrue(comparison['limitations'])
        self.assertIn('pp',format_comparison(comparison));self.assertIn('Saved analysis comparison',comparison_html(comparison))
    def test_old_reports_and_stats_only_keep_missing_values(self):
        a=entry(sample());b=copy.deepcopy(a);b['payload'].pop('metric_records');b['payload'].pop('fight_evidence');b['payload']['result_state']='comparison'
        compared=compare_entries(a,b)
        self.assertEqual(compared['probability'],[]);self.assertEqual(compared['metrics'],[]);self.assertGreaterEqual(len(compared['limitations']),3)
    def test_changed_definition_is_not_subtracted(self):
        a=entry(sample());b=copy.deepcopy(a);b['payload']['metric_records'][0]['semantic_version']=2
        rows=compare_entries(a,b)['metrics'];self.assertIsNone(rows[0]['delta'])
    def test_new_metric_is_unavailable_in_original_without_inventing_zero(self):
        a=entry(sample());b=copy.deepcopy(a)
        b['payload']['metric_records'].append(dict(id='new',semantic_version=1,unit='count',window='history',label='New metric',raw_a=3,raw_b=None))
        rows=[r for r in compare_entries(a,b)['metrics'] if r['metric_id']=='new']
        self.assertIsNone(rows[0]['before']);self.assertIsNone(rows[0]['delta']);self.assertEqual(rows[0]['after'],3)
    def test_percentage_metric_deltas_use_percentage_points(self):
        a=entry(sample());b=copy.deepcopy(a)
        a['payload']['metric_records']=[dict(id='accuracy',semantic_version=1,unit='percent',window='last five',label='Accuracy',raw_a=.5,raw_b=None)]
        b['payload']['metric_records']=copy.deepcopy(a['payload']['metric_records']);b['payload']['metric_records'][0]['raw_a']=.6
        self.assertAlmostEqual(compare_entries(a,b)['metrics'][0]['delta'],10)
    def test_fight_evidence_distinguishes_records_from_last_five(self):
        a=entry(sample());b=copy.deepcopy(a);b['payload']['fight_evidence']['fighter_a'][0]['content_fingerprint']='new'
        self.assertEqual(compare_entries(a,b)['fights'][0]['change'],'record changed')
    def test_comparison_is_snapshot_after_original_mutation(self):
        a=entry(sample());b=copy.deepcopy(a);value=compare_entries(a,b);a['payload']['fighter_a']='changed'
        self.assertNotEqual(value['original']['payload']['fighter_a'],'changed')
    def test_saved_frozen_summary_and_provenance_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            history=History(folder);p=sample();history.save({'sex':'men','operation':'predict'},{},p)
            saved=history.entries()[0]['payload']
            self.assertEqual(saved['matchup_summary'],p['matchup_summary']);self.assertEqual(saved['fight_evidence'],p['fight_evidence'])

class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.rows=[dict(fight_id='f',event_date='2020-01-01',event_name='Example',fighter='A',profile_url='http://source/a',won='1',result='win',td_landed='2'),dict(fight_id='f',event_date='2020-01-01',event_name='Example',fighter='B',profile_url='http://source/b',won='0',result='loss',td_landed='0')]
        write_rows(self.root/SOURCE_PATHS['women'][0],self.rows)
        self.capture=dict(events=[dict(event_id='e',event_name='Example',event_date='2020-01-01')],tables={SOURCE_PATHS['women'][0]:copy.deepcopy(self.rows)})
    def tearDown(self):self.temp.cleanup()
    def test_numeric_format_and_order_do_not_create_corrections(self):
        self.capture['tables'][SOURCE_PATHS['women'][0]].reverse()
        self.capture['tables'][SOURCE_PATHS['women'][0]][0]['td_landed']='0.0'
        self.assertEqual(diff_capture(self.root,'women',self.capture),[])
        self.assertIsNone(canonical(''));self.assertNotEqual(canonical(''),canonical('0'))
        self.assertEqual(canonical('2020-01-01 00:00:00'),canonical('2020-01-01'))
    def test_missing_pair_and_identity_changes_block(self):
        self.capture['tables'][SOURCE_PATHS['women'][0]].pop()
        with self.assertRaises(ValueError):diff_capture(self.root,'women',self.capture)
        self.capture['tables'][SOURCE_PATHS['women'][0]]=copy.deepcopy(self.rows)
        self.capture['tables'][SOURCE_PATHS['women'][0]][0]['profile_url']='http://source/c'
        with self.assertRaises(ValueError):diff_capture(self.root,'women',self.capture)
    def test_absent_known_bout_cannot_be_deleted(self):
        self.capture['tables'][SOURCE_PATHS['women'][0]]=[]
        with self.assertRaises(ValueError):diff_capture(self.root,'women',self.capture)
    def test_full_pair_replacement_is_idempotent_and_keeps_unrelated(self):
        old=copy.deepcopy(self.rows)
        for r in old:r['fight_id']='unrelated';r['event_date']='2019-01-01'
        write_rows(self.root/SOURCE_PATHS['women'][0],self.rows+old)
        for r in self.capture['tables'][SOURCE_PATHS['women'][0]]:r['result']='nc';r['won']=''
        changes=[dict(sex='women',**c) for c in diff_capture(self.root,'women',self.capture)]
        apply_source(self.root,'women',self.capture,changes)
        result_rows=read_rows(self.root/SOURCE_PATHS['women'][0]);self.assertEqual(len(result_rows),4)
        self.assertEqual([r for r in result_rows if r['fight_id']=='unrelated'],old)
        self.assertEqual(diff_capture(self.root,'women',self.capture),[])
    def test_corrupted_or_stale_preview_refused(self):
        identifier='20261012T000000-1234abcd';path=self.root/'.runtime/corrections'/identifier/'preview.json';path.parent.mkdir(parents=True)
        value=dict(schema=1,id=identifier,baseline={},captures={},changes=[]);value['integrity']='bad';path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):validate_preview(self.root,identifier)
        with self.assertRaises(ValueError):validate_preview(self.root,'../unsafe')
    def test_changed_installed_hash_rejects_authentic_preview(self):
        from analyzer_support import digest
        rel=SOURCE_PATHS['women'][0];identifier='20261012T000000-1234abcd'
        value=dict(schema=1,id=identifier,baseline={rel:digest(self.root/rel)},captures={},changes=[]);value['integrity']=fingerprint(value)
        path=self.root/'.runtime/corrections'/identifier/'preview.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(value))
        (self.root/rel).write_text('changed')
        with self.assertRaisesRegex(ValueError,'Installed datasets changed'):validate_preview(self.root,identifier)
    def test_all_completed_result_transitions_have_consistent_targets(self):
        for sex in ('men','women'):
            for results,targets in ((('win','loss'),('1','0')),(('loss','win'),('0','1')),(('draw','draw'),('','')),(('no_contest','no_contest'),('',''))):
                rows=copy.deepcopy(self.rows)
                for r,result,target in zip(rows,results,targets):r.update(result=result,won=target)
                validate_pair(rows,sex,'f')
                rows[0]['won']='1' if targets[0]!='1' else ''
                with self.assertRaises(ValueError):validate_pair(rows,sex,'f')
    def test_stat_correction_keeps_pair_and_is_repeatable(self):
        self.capture['tables'][SOURCE_PATHS['women'][0]][0]['td_landed']='3'
        changes=diff_capture(self.root,'women',self.capture)
        self.assertEqual(changes[0]['differences'][0]['field'],'td_landed')
        apply_source(self.root,'women',self.capture,[dict(sex='women',**c) for c in changes])
        self.assertEqual(diff_capture(self.root,'women',self.capture),[])
    def test_changed_event_metadata_does_not_hide_a_missing_known_bout(self):
        write_rows(self.root/'mens_ufc_model/data/raw/ufcstats_men/events.csv',[dict(event_id='e',event_name='Example',event_date='2020-01-01')])
        self.capture['events'][0].update(event_name='New event name',event_date='2020-01-02')
        self.capture['tables'][SOURCE_PATHS['women'][0]]=[]
        with self.assertRaisesRegex(ValueError,'Known bouts are missing'):diff_capture(self.root,'women',self.capture)
    def test_name_changes_require_reconciliation_in_name_based_engine(self):
        self.capture['tables'][SOURCE_PATHS['women'][0]][0]['fighter']='New identity alias'
        with self.assertRaisesRegex(ValueError,'name changed'):diff_capture(self.root,'women',self.capture)
    def test_mens_linked_result_and_identity_are_reaudited(self):
        fights=[dict(fight_id='f',event_id='e',event_date='2020-01-01',fighter_red_id='a',fighter_blue_id='b',winner_id='a',loser_id='b',result='win_loss')]
        stats=[dict(fight_id='f',event_id='e',event_date='2020-01-01',fighter_id=identity,result=result,won=target) for identity,result,target in [('a','win','1'),('b','loss','0')]]
        for rel,rows in zip(SOURCE_PATHS['men'],(fights,stats)):write_rows(self.root/rel,rows)
        capture=dict(events=[dict(event_id='e',event_name='Example',event_date='2020-01-01')],tables=dict(zip(SOURCE_PATHS['men'],(copy.deepcopy(fights),copy.deepcopy(stats)))))
        self.assertEqual(diff_capture(self.root,'men',capture),[])
        capture['tables'][SOURCE_PATHS['men'][0]][0].update(result='no_contest',winner_id='',loser_id='')
        with self.assertRaisesRegex(ValueError,'outcomes disagree'):diff_capture(self.root,'men',capture)

class CorrectionTransactionTests(unittest.TestCase):
    def test_second_target_and_mid_promotion_failures_restore_both(self):
        import analyzer_corrections as corrections
        import analyzer_maintenance as maintenance
        from analyzer_support import atomic_json,digest
        actual_promote=maintenance.promote
        for phase in ('second_target','promotion'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);files=[]
                for sex,engine in maintenance.ENGINE.items():
                    rel=engine+'/data/example.csv';path=root/rel;path.parent.mkdir(parents=True);path.write_text('event_date,value\n2020-01-01,1\n')
                    files.append(dict(path=rel,sha256=digest(path),size_bytes=path.stat().st_size,rows=1,columns=['event_date','value']))
                atomic_json(root/'dataset_manifest.json',dict(files=files))
                for helper in ('analyzer_protocol.py','analyzer_errors.py'):(root/helper).write_text('')
                original={e['path']:(root/e['path']).read_bytes() for e in files}
                preview=dict(changes=[dict(sex=s,fight_id='f',kind='corrected') for s in ('men','women')],captures={s:{} for s in ('men','women')})
                def source(stage,sex,*unused):
                    (stage/maintenance.ENGINE[sex]/'data/example.csv').write_text('event_date,value\n2020-01-01,2\n')
                def rebuild(stage,sex,*unused):
                    staged_journal=json.loads((stage.parent/'journal.json').read_text())
                    self.assertEqual(staged_journal['status'],'staging')
                    self.assertEqual(staged_journal['promotions'],[])
                    if phase=='second_target' and sex=='women':raise RuntimeError('second target failed')
                def promotion(root,stage,txn,journal,files):
                    actual_promote(root,stage,txn,journal,[next(rel for rel in files if rel.endswith('example.csv'))])
                    raise RuntimeError('promotion interrupted')
                with mock.patch.object(corrections,'validate_preview',return_value=preview),mock.patch.object(corrections,'apply_source',side_effect=source),mock.patch.object(maintenance,'rebuild_engine',side_effect=rebuild),mock.patch.object(maintenance,'promote',side_effect=promotion if phase=='promotion' else AssertionError('Early promotion')):
                    with self.assertRaisesRegex(RuntimeError,'failed|interrupted'):corrections.apply(root,'reviewed',runner=lambda *unused:None,validator=lambda *unused:None)
                self.assertEqual(original,{rel:(root/rel).read_bytes() for rel in original})
                journals=list((root/'.runtime/transactions').glob('*/journal.json'))
                self.assertEqual(json.loads(journals[0].read_text())['status'],'rolled_back')
                self.assertFalse((root/'.runtime/maintenance.lock').exists())

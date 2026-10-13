"""Initial evidence, frozen charts, reviewed import and recovery contracts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from analyzer_history import History,fingerprint
from analyzer_migration import preview,apply,undo,recover,preferences,valid_entry
from analyzer_support import atomic_json,digest
from analyzer_visuals import build_visual_evidence,format_visuals,html_visuals
from analyzer_validation import load_report
from analyzer_quick_comparison import build_quick
from analyzer_catalog import FighterCatalog
from test_gui import result,catalogue_fixture,FakeController
from analyzer_results import format_result

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.source=self.base/'old';self.target=self.base/'new'
        for root in (self.source,self.target):root.mkdir();(root/'analyzer_support.py').write_text('');(root/'.runtime/history').mkdir(parents=True)
        payload=result();payload.update(result_state='complete',generated_at='2026-01-01T00:00:00+00:00',training_rows=100)
        request=dict(operation='predict',sex='men',fighter_a=payload['fighter_a'],fighter_b=payload['fighter_b'],fight_date=payload['fight_date'])
        self.id=History(self.source).save(request,{},payload)
        self.original={p.name:digest(p) for p in (self.source/'.runtime/history').glob('*.json')}
    def tearDown(self):self.temp.cleanup()
    def test_import_preserves_original_and_repeat_is_duplicate(self):
        value=preview(self.target,self.source);self.assertEqual(value['counts']['valid'],1)
        apply(self.target,value['id']);self.assertEqual(len(History(self.target).entries()),1)
        self.assertEqual(self.original,{p.name:digest(p) for p in (self.source/'.runtime/history').glob('*.json')})
        self.assertEqual(preview(self.target,self.source)['counts']['duplicate'],1)
        repeat=preview(self.target,self.source);apply(self.target,repeat['id']);undo(self.target)
        self.assertFalse(History(self.target).entries())
    def test_self_and_nested_sources_are_rejected(self):
        with self.assertRaises(ValueError):preview(self.source,self.source)
    def test_changed_capture_is_rejected(self):
        value=preview(self.target,self.source);path=self.source/'.runtime/history'/(self.id+'.json');path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):apply(self.target,value['id'])
        self.assertFalse(History(self.target).entries())
    def test_corrupt_unknown_and_oversized_records_are_counted(self):
        (self.source/'.runtime/history/bad.json').write_text('{')
        entry=History(self.source).entries()[0]
        for number,change in ((1,dict(schema=2)),(2,dict(created_at='not a date')),(3,dict(payload=dict(entry['payload'],fight_date='invalid'),request=dict(entry['request'],fight_date='invalid'))),(4,dict(payload=dict(entry['payload'],visual_evidence=dict(schema=99,bars=[],elo={}))))):
            changed=copy.deepcopy(entry);changed.update(change,id=f'{number:032x}')
            changed['cache_key']=fingerprint(dict(request=changed['request'],context=changed['context']))
            changed['integrity']=fingerprint({k:v for k,v in changed.items() if k!='integrity'})
            atomic_json(self.source/'.runtime/history'/(changed['id']+'.json'),changed)
        (self.source/'.runtime/history/oversized.json').write_text(' '*(8*1024*1024+1))
        value=preview(self.target,self.source);self.assertEqual(value['counts']['invalid'],6)
        self.assertEqual(value['counts']['valid'],1)
    def test_conflicting_identity_is_not_replaced(self):
        source=History(self.source).entries()[0];other=copy.deepcopy(source);other['payload']['generated_at']='different';other['integrity']=fingerprint({k:v for k,v in other.items() if k!='integrity'})
        atomic_json(self.target/'.runtime/history'/(self.id+'.json'),other)
        self.assertEqual(preview(self.target,self.source)['counts']['conflict'],1)
    def test_full_destination_is_preserved(self):
        for i in range(50):(self.target/'.runtime/history'/f'{i:032x}.json').write_text('{}')
        value=preview(self.target,self.source);self.assertEqual(value['counts']['over_budget'],1)
        apply(self.target,value['id']);self.assertEqual(len(list((self.target/'.runtime/history').glob('*.json'))),50)
    def test_preferences_are_allowlisted_and_destination_storage_setting_survives(self):
        atomic_json(self.source/'.runtime/ui_preferences.json',dict(text_size='Large',history_enabled=True,save_directory='unsafe',geometry='900x700'))
        atomic_json(self.target/'.runtime/ui_preferences.json',dict(history_enabled=False,text_size='Small'))
        value=preview(self.target,self.source);apply(self.target,value['id'],True)
        current=json.loads((self.target/'.runtime/ui_preferences.json').read_text());self.assertEqual(current,dict(history_enabled=False,text_size='Large',geometry='900x700'))
        undo(self.target);self.assertEqual(json.loads((self.target/'.runtime/ui_preferences.json').read_text()),dict(history_enabled=False,text_size='Small'))
    def test_remembered_selections_are_checked_against_current_catalog(self):
        catalogue_fixture(self.target)
        atomic_json(self.source/'.runtime/ui_preferences.json',dict(division='Men — Lightweight',fighter_a='Jose Alpha',fighter_b='Deleted fighter'))
        value=preview(self.target,self.source)
        self.assertEqual(value['preferences']['fighter_a'],'José Alpha');self.assertEqual(value['preferences']['fighter_b'],'')
        apply(self.target,value['id'],True)
        self.assertEqual(json.loads((self.target/'.runtime/ui_preferences.json').read_text())['division'],'Men — Lightweight')
    def test_cancel_before_commit_and_low_space_preserve_history(self):
        from analyzer_runtime import Cancelled
        value=preview(self.target,self.source)
        with self.assertRaises(Cancelled):apply(self.target,value['id'],cancel=lambda:True)
        with mock.patch('analyzer_migration.shutil.disk_usage',return_value=mock.Mock(free=1)),self.assertRaises(OSError):apply(self.target,value['id'])
        self.assertFalse(History(self.target).entries())
    def test_reviewed_selection_and_unknown_ids(self):
        value=preview(self.target,self.source)
        with self.assertRaises(ValueError):apply(self.target,value['id'],selected_ids=['unreviewed'])
        apply(self.target,value['id'],selected_ids=[]);self.assertFalse(History(self.target).entries())
        apply(self.target,value['id'],selected_ids=[self.id]);self.assertEqual(len(History(self.target).entries()),1)
    def test_undo_retains_changed_records(self):
        value=preview(self.target,self.source);apply(self.target,value['id']);path=self.target/'.runtime/history'/(self.id+'.json');path.write_text('changed')
        message=undo(self.target)['message'];self.assertIn('Changed files retained',message);self.assertEqual(path.read_text(),'changed')
    def test_interrupted_commit_recovers_only_owned_records(self):
        value=preview(self.target,self.source);apply(self.target,value['id'])
        path=next((self.target/'.runtime/imports').glob('*.json'));journal=json.loads(path.read_text());journal['status']='committing';atomic_json(path,journal)
        staging=self.target/'.runtime/import_staging'/journal['id'];staging.mkdir(parents=True)
        staged=staging/(self.id+'.json');staged.write_bytes((self.target/'.runtime/history'/(self.id+'.json')).read_bytes())
        kept=staging/'unrelated.json';kept.write_text('{}')
        unrelated=self.target/'.runtime/history/keep.json';unrelated.write_text('{}');recover(self.target)
        self.assertTrue(unrelated.exists());self.assertFalse((self.target/'.runtime/history'/(self.id+'.json')).exists());recover(self.target)
        self.assertFalse(staged.exists());self.assertTrue(kept.exists())

class EvidenceTests(unittest.TestCase):
    def test_metadata_scan_handles_quoted_newlines_blank_and_invalid_dates(self):
        from analyzer_support import csv_info
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'records.csv'
            path.write_text('event_date,text\n2020-01-01,"two\nlines"\n\n2020-01-01,repeat\ninvalid,bad\n9999-01-01,future\n,missing\n',encoding='utf-8')
            info=csv_info(path);self.assertEqual(info['rows'],5);self.assertEqual(info['invalid_or_future_dates'],2)
            self.assertEqual(info['columns'],['event_date','text']);self.assertEqual(info['latest_date'],'9999-01-01')
    def test_frozen_visuals_and_escaped_exports(self):
        payload=result();payload['fighter_a']='<script>x</script>';payload['fighter_a_comparison']=dict(career_slpm_before=0,career_td_defense_before=.7)
        payload['fighter_b_comparison']=dict(career_slpm_before=2,career_td_defense_before=None)
        record=build_visual_evidence(payload);payload['visual_evidence']=record
        self.assertEqual(record['bars'][0]['a'],0);self.assertIsNone(record['bars'][1]['b'])
        payload['fighter_a_comparison']['career_slpm_before']=99
        self.assertIn('A 0.00',format_visuals(payload));self.assertNotIn('<script>',html_visuals(payload));self.assertIn('N/A',html_visuals(payload))
    def test_old_report_does_not_invent_elo(self):
        payload=result();self.assertFalse(build_visual_evidence(payload)['elo'])
    def test_initial_has_no_probability_and_is_not_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);catalogue_fixture(root);catalog=FighterCatalog('men',root)
            request=dict(sex='men',fighter_a='Jose Alpha',fighter_b='Beta',fighter_a_id='1',fighter_b_id='2',division='Lightweight',fight_date='2020-01-01',effective_cutoff='2019-12-31')
            coverage={s:dict(fights=0,division_fights=0) for s in ('a','b')}
            recent=dict(history_cutoff='2020-01-01',fighter_a=[],fighter_b=[])
            payload=build_quick(root,request,catalog,recent,coverage,dict(engine='v3_bayes_smoothed'))
            self.assertNotIn('fighter_a_win_probability',payload);self.assertIn('partial evidence',format_result(payload))
            self.assertIsNone(History(root).save(request,{},payload))
    def test_validation_rejects_modified_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'docs').mkdir();atomic_json(root/'docs/model_validation.json',dict(schema=1,integrity='wrong'))
            with self.assertRaises(ValueError):load_report(root)

class InitialWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name!='nt' and not os.environ.get('DISPLAY'):raise unittest.SkipTest('Native window requires a graphical display')
    def test_initial_event_and_cancellation_keep_partial_report(self):
        import tkinter as tk
        from analyzer_gui import AnalyzerApp
        with tempfile.TemporaryDirectory() as temp:
            window=tk.Tk();window.withdraw();controller=FakeController();app=AnalyzerApp(window,Path(temp),controller,False)
            try:
                payload=result();payload.update(result_state='initial',quick_comparison=True,coverage={s:dict(fights=0,division_fights=0) for s in ('a','b')},training_cutoff='2020-01-01')
                payload.update(fighter_a_comparison={},fighter_b_comparison={})
                payload.pop('fighter_a_win_probability');payload.pop('fighter_b_win_probability')
                controller.poll=lambda:[dict(type='initial_ready',payload=payload)];controller.busy=True;app.stage_message='Preparing';app.last_request={'operation':'predict'}
                app.poll();self.assertTrue(app.result['quick_comparison']);self.assertIn('partial',app.summary.get())
                app.handle_terminal(dict(type='error',code='cancelled',message='Cancelled'))
                self.assertEqual(app.result['result_state'],'cancelled');self.assertIn('partial evidence',app.result_text)
            finally:controller.busy=False;app.destroy()
    def test_import_and_undo_apply_preferences_to_live_controls(self):
        import tkinter as tk
        from analyzer_gui import AnalyzerApp
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);catalogue_fixture(root);window=tk.Tk();window.withdraw()
            app=AnalyzerApp(window,root,FakeController(),False)
            try:
                with mock.patch('analyzer_gui.messagebox.showinfo'):
                    app.handle_terminal(dict(type='result',operation='import_history',payload=dict(message='Imported',preferences=dict(text_size='Large',inputs_collapsed=True,geometry='900x700',division='Men — Lightweight',fighter_a='Jose Alpha',fighter_b='Beta'))))
                    self.assertTrue(app.collapsed);self.assertEqual(app.font_size.get(),'Large');self.assertEqual(app.names['a'].get(),'Jose Alpha')
                    app.handle_terminal(dict(type='result',operation='undo_import',payload=dict(message='Undone',preferences_snapshot=dict(text_size='Small',inputs_collapsed=False,history_enabled=False))))
                    self.assertFalse(app.collapsed);self.assertEqual(app.font_size.get(),'Small');self.assertFalse(app.history_setting.get())
            finally:app.destroy()

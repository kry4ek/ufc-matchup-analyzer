"""User-visible behavior, operation exclusion and update failure guarantees."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from analyzer_catalog import FighterCatalog,IdentityError,validate_matchup,key
from analyzer_results import format_result,result_filename
from analyzer_runtime import Cancelled,ProcessTree,operation_lock,python_executable,subprocess_options
import analyzer_runtime as runtime
import analyzer_maintenance as maintenance
from test_safety import mini_root

def catalogue_fixture(root):
    path=root/'mens_ufc_model/data/raw/ufcstats_men/fighters.csv';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('fighter_name,fighter_id,date_of_birth,weight\nJosé Alpha,a,1990-01-01,155 lbs.\nOther Fighter,b,1992-01-01,170 lbs.\nSame Name,c,1980-01-01,185 lbs.\nSame Name,d,1995-01-01,125 lbs.\n',encoding='utf-8')
    path=root/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('fighter,profile_url,event_date\nWoman Alpha,http://example/a,2020-01-01\nWoman Beta,http://example/b,2020-01-01\n',encoding='utf-8')

class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);catalogue_fixture(self.root);self.catalog=FighterCatalog('men',self.root)
    def tearDown(self):self.temp.cleanup()
    def test_accents_case_and_search(self):
        self.assertEqual(self.catalog.resolve('JOSE ALPHA'),('José Alpha','a'))
        self.assertEqual(self.catalog.search('alpha'),['José Alpha'])
        self.assertIn('born: 1980-01-01',self.catalog.describe(('Same Name','c')))
    def test_suggestions_never_substitute(self):
        with self.assertRaises(IdentityError) as error:self.catalog.resolve('Jose Alhpa')
        self.assertIn(('José Alpha','a'),error.exception.candidates)
        with self.assertRaises(IdentityError) as distant:self.catalog.resolve('zzzzzz')
        self.assertEqual(distant.exception.candidates,[])
    def test_explicit_duplicate_identity(self):
        with self.assertRaises(IdentityError) as error:self.catalog.resolve('Same Name')
        self.assertTrue(error.exception.ambiguous)
        self.assertEqual(self.catalog.resolve('same name','d'),('Same Name','d'))
    def test_same_fighter_and_invalid_division(self):
        for division,a,b in [('Lightweight',('A','a'),('A','a')),('Imaginary',('A','a'),('B','b'))]:
            with self.assertRaises(ValueError):validate_matchup('men',division,'2020-01-01',a,b)

def result():
    return dict(fighter_a='José Alpha',fighter_b='Other Fighter',fight_date='2026-10-10',division='Lightweight',fighter_a_win_probability=.6,fighter_b_win_probability=.4,predicted_winner='José Alpha',model_version='v3_bayes_smoothed',confidence_tier='medium',warnings=['Limited history'],elapsed_seconds=100)

class ResultTests(unittest.TestCase):
    def test_text_contains_context_and_warnings(self):
        text=format_result(result())
        for value in ('José Alpha vs Other Fighter','60.0%','40.0%','2026-10-10','Limited history','v3_bayes_smoothed'):self.assertIn(value,text)
    def test_filename_sanitization(self):
        self.assertEqual(result_filename(result()),'José Alpha vs Other Fighter.txt')
        self.assertNotIn('/',result_filename(dict(result(),fighter_a='A/B:*?',fighter_b='C\\D')))
        self.assertLess(len(result_filename(dict(result(),fighter_a='A'*400))),200)

class RuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows ASCII worker-path adapter')
    def test_unicode_temp_path_and_no_short_name_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'André';folder.mkdir()
            short=runtime.ascii_temp_directory(folder);self.assertTrue(short.isascii())
            with mock.patch.object(runtime,'windows_short_path',return_value=''):
                alias=runtime.ascii_temp_directory(folder);self.assertTrue(alias.isascii())
                (Path(alias)/'test.txt').write_text('inside app',encoding='utf-8')
                self.assertEqual((folder/'test.txt').read_text(),'inside app')
                runtime.release_temp_aliases()
    def test_cv_failure_is_never_silently_reweighted(self):
        import importlib.util
        import numpy as np
        spec=importlib.util.spec_from_file_location('women_weight_guard',ROOT/'womens_ufc_model/predict_matchup_advanced.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        with mock.patch.object(module,'cross_val_score',side_effect=PermissionError('worker blocked')),self.assertRaisesRegex(RuntimeError,'fallback weights'):
            module.compute_model_weights({'model':object()},np.zeros((6,1)),np.array([0,1]*3))
    def test_cross_process_lock_and_crash_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            script='import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from analyzer_runtime import operation_lock;\nwith operation_lock(Path(sys.argv[2])):print("acquired")'
            with operation_lock(root):
                process=subprocess.run([python_executable(),'-c',script,str(ROOT),str(root)],capture_output=True,text=True,**subprocess_options())
                self.assertNotEqual(process.returncode,0);self.assertIn('Another analysis',process.stderr)
            process=subprocess.run([python_executable(),'-c',script,str(ROOT),str(root)],capture_output=True,text=True,**subprocess_options())
            self.assertEqual(process.returncode,0,process.stderr)
    def test_process_tree_cancellation(self):
        with tempfile.TemporaryDirectory() as temp:
            pidfile=Path(temp)/'child.pid'
            code='import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"]);Path(sys.argv[1]).write_text(str(p.pid));time.sleep(120)'
            process=subprocess.Popen([python_executable(),'-c',code,str(pidfile)],**subprocess_options());tree=ProcessTree(process)
            try:
                end=time.monotonic()+10
                while not pidfile.exists() and time.monotonic()<end:time.sleep(.05)
                self.assertTrue(pidfile.exists());pid=int(pidfile.read_text())
                tree.terminate();time.sleep(.2)
                self.assertFalse(maintenance.process_alive(pid),'Descendant survived cancellation')
            finally:tree.close()

class UpdateBehaviorTests(unittest.TestCase):
    def test_unchanged_update_skips_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mini_root(root)
            def runner(cmd,cwd,log):
                path=cwd/'_update_manifests/run';path.mkdir(parents=True)
                (path/'new_rows_safety_audit.json').write_text('{"unsafe_rows_count":0}')
            with mock.patch.object(maintenance,'rebuild_engine') as rebuild:
                transaction=maintenance.maintenance(root,target='men',apply=True,runner=runner)
                rebuild.assert_not_called()
            journal=json.loads((root/'.runtime/transactions'/transaction/'journal.json').read_text())
            self.assertEqual(journal['status'],'no_changes');self.assertFalse((root/'.runtime/local_dataset_state.json').exists())
    def test_insufficient_space_before_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mini_root(root)
            with mock.patch.object(maintenance.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(100,99,1)),self.assertRaisesRegex(RuntimeError,'Not enough free space'):
                maintenance.maintenance(root,target='men',apply=True)
            self.assertFalse((root/'.runtime/transactions').exists())
    def test_cancel_before_commit_preserves_installed_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=mini_root(root);path=root/spec['files'][0]['path'];before=path.read_bytes();cancelled=[False]
            def validator(stage,*args):
                (stage/spec['files'][0]['path']).write_text('event_date,value\n2020-01-01,2\n');cancelled[0]=True
            with self.assertRaises(Cancelled):maintenance.maintenance(root,kind='rebuild',target='men',runner=lambda *a:None,validator=validator,cancel=lambda:cancelled[0])
            self.assertEqual(path.read_bytes(),before)
    def test_interrupted_commit_restored_at_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=mini_root(root);rel=spec['files'][0]['path'];before=(root/rel).read_bytes()
            txn=root/'.runtime/transactions/crash';stage=txn/'stage';(stage/rel).parent.mkdir(parents=True);(stage/rel).write_text('new')
            journal=dict(id='crash',status='staging',promotions=[],pid=-1)
            maintenance.promote(root,stage,txn,journal,[rel]);journal['status']='committing';(txn/'journal.json').write_text(json.dumps(journal))
            (root/'.runtime/maintenance.lock').write_text(json.dumps(dict(transaction='crash',pid=-1)))
            self.assertEqual(maintenance.recover_interrupted(root),['crash']);self.assertEqual((root/rel).read_bytes(),before)
    def test_backup_and_log_retention(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mini_root(root)
            for n in range(12):
                directory=root/'.runtime/transactions'/f'{n:02}';(directory/'before').mkdir(parents=True);(directory/'before/backup').write_text('data')
                (directory/'journal.json').write_text(json.dumps(dict(id=f'{n:02}',status='committed')))
            (root/'.runtime/local_dataset_state.json').write_text('{"transaction":"05"}')
            maintenance.cleanup_history(root)
            self.assertTrue((root/'.runtime/transactions/05/before/backup').exists())
            self.assertFalse((root/'.runtime/transactions/11/before').exists())
            self.assertLessEqual(len(list((root/'.runtime/transactions').iterdir())),11)

class FakeController:
    busy=False;cancellable=False;started=0
    def start(self,request):self.request=request;self.busy=True;self.started=time.monotonic()
    def cancel(self):self.cancelled=True;return self.cancellable
    def poll(self):return []
    def terminate(self):self.busy=False

class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name!='nt' and not os.environ.get('DISPLAY'):raise unittest.SkipTest('No graphical display; run Windows package GUI checks')
        import analyzer_gui
        cls.gui=analyzer_gui
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);catalogue_fixture(self.root)
        self.window=self.gui.tk.Tk();self.window.withdraw();self.controller=FakeController();self.app=self.gui.AnalyzerApp(self.window,self.root,self.controller,autostart=False)
        self.app.ready=True;self.app.catalogs={s:FighterCatalog(s,self.root) for s in ('men','women')};self.app.controls()
    def tearDown(self):self.app.destroy();self.temp.cleanup()
    def test_names_date_and_same_fighter_validation(self):
        self.app.names['a'].set('jose alpha');self.app.names['b'].set('Other Fighter')
        request=self.app.prediction_request();self.assertEqual(request['fighter_a'],'José Alpha');self.assertEqual(request['sex'],'men')
        self.app.date.set('2026-02-30')
        with self.assertRaises(argparse.ArgumentTypeError):self.app.prediction_request()
        self.app.date.set('2026-10-10');self.app.names['b'].set('José Alpha')
        with self.assertRaises(ValueError):self.app.prediction_request()
    def test_explicit_suggestion_and_duplicate_selection(self):
        self.app.names['a'].set('Jose Alhpa');self.app.names['b'].set('Other Fighter')
        with mock.patch.object(self.app,'choose_identity',return_value=('José Alpha','a')) as choice:
            self.assertEqual(self.app.prediction_request()['fighter_a'],'José Alpha');choice.assert_called_once()
        self.app.names['a'].set('Same Name');self.app.selection.clear()
        with mock.patch.object(self.app,'choose_identity',return_value=('Same Name','d')):
            self.assertEqual(self.app.prediction_request()['fighter_a_id'],'d')
    def test_suggestion_cancel_does_not_start_training(self):
        self.app.names['a'].set('Jose Alhpa');self.app.names['b'].set('Other Fighter')
        with mock.patch.object(self.app,'choose_identity',return_value=None):self.app.analyze()
        self.assertFalse(self.controller.busy)
    def test_actual_identity_dialog_requires_selection(self):
        error=IdentityError('Choose the right fighter',[('Same Name','c'),('Same Name','d')],True)
        def select():
            for dialog in self.window.winfo_children():
                if not isinstance(dialog,self.gui.tk.Toplevel):continue
                choices=next(c for c in dialog.winfo_children() if isinstance(c,self.gui.tk.Listbox));choices.selection_set(1)
                buttons=next(c for c in dialog.winfo_children() if isinstance(c,self.gui.ttk.Frame))
                next(c for c in buttons.winfo_children() if isinstance(c,self.gui.ttk.Button) and c['text']=='Use selected fighter').invoke()
        self.window.after(100,select)
        self.assertEqual(self.app.choose_identity('a',error,self.app.catalogs['men']),('Same Name','d'))
    def test_close_during_commit_waits_and_close_during_analysis_cancels(self):
        self.controller.busy=True;self.controller.cancellable=False
        with mock.patch.object(self.gui.messagebox,'showinfo') as info:self.app.close();info.assert_called_once()
        self.assertFalse(self.app.closing)
        self.controller.cancellable=True
        with mock.patch.object(self.gui.messagebox,'askyesno',return_value=True):self.app.close()
        self.assertTrue(self.app.closing);self.assertTrue(self.controller.cancelled)
    def test_missing_data_disables_analysis_and_surfaces_details(self):
        payload=dict(ready=False,dates=dict(men='Unknown',women='Unknown'),checks=[dict(path='missing.csv',status='FAIL',message='Missing data')])
        with mock.patch.object(self.gui.messagebox,'showerror'):self.app.handle_terminal(dict(type='result',operation='doctor',payload=payload))
        self.app.controls();self.assertFalse(self.app.ready);self.assertEqual(str(self.app.analyze_button['state']),'disabled');self.assertIn('Missing data',self.app.output.get('1.0','end'))
    def test_results_remain_bound_to_completed_matchup(self):
        self.app.handle_terminal(dict(type='result',operation='predict',payload=result()))
        self.app.names['a'].set('Someone Else');self.app.copy();self.window.update()
        self.assertEqual(self.window.clipboard_get(),self.app.result_text)
        self.assertIn('José Alpha vs Other Fighter',self.app.result_text)
    def test_failed_installation_check_preserves_displayed_analysis(self):
        self.app.handle_terminal(dict(type='result',operation='predict',payload=result()))
        expected=self.app.result_text
        payload=dict(ready=False,dates=dict(men='Unknown',women='Unknown'),checks=[dict(path='missing.csv',status='FAIL',message='Missing data')])
        with mock.patch.object(self.gui.messagebox,'showerror'):self.app.handle_terminal(dict(type='result',operation='doctor',payload=payload))
        self.app.controls();self.app.copy();self.window.update()
        self.assertFalse(self.app.ready);self.assertEqual(self.app.output.get('1.0','end-1c'),expected);self.assertEqual(self.window.clipboard_get(),expected)
        dest=self.root/'saved.txt'
        with mock.patch.object(self.gui.filedialog,'asksaveasfilename',return_value=str(dest)) as save:
            self.app.save();self.assertEqual(save.call_args.kwargs['initialfile'],'José Alpha vs Other Fighter.txt')
        self.assertEqual(dest.read_text(encoding='utf-8'),self.app.result_text)
    def test_save_cancel_does_not_create_file(self):
        self.app.handle_terminal(dict(type='result',operation='predict',payload=result()))
        with mock.patch.object(self.gui.filedialog,'asksaveasfilename',return_value=''):self.app.save()
        self.assertFalse(list(self.root.glob('*.txt')))
    def test_html_save_action_sets_native_filename_and_format(self):
        self.app.handle_terminal(dict(type='result',operation='predict',payload=result()))
        destination=self.root/'José Alpha vs Other Fighter.html'
        with mock.patch.object(self.gui.filedialog,'asksaveasfilename',return_value=str(destination)) as dialog:
            self.app.save_menu.invoke(1)
        self.assertEqual(dialog.call_args.kwargs['initialfile'],destination.name)
        self.assertEqual(dialog.call_args.kwargs['defaultextension'],'.html')
        self.assertEqual(dialog.call_args.kwargs['filetypes'],[('HTML report','*.html')])
        self.assertIn('<!doctype html>',destination.read_text(encoding='utf-8').lower())
    def test_repeated_analyze_is_blocked_and_committing_cannot_cancel(self):
        self.app.names['a'].set('José Alpha');self.app.names['b'].set('Other Fighter');self.app.analyze()
        request=dict(self.controller.request);self.app.analyze();self.assertEqual(self.controller.request,request)
        self.controller.cancellable=False;self.app.controls();self.assertEqual(str(self.app.cancel_button['state']),'disabled')
    def test_idle_polling_does_not_reconfigure_help_menu(self):
        # A redundant native menu configuration redraws an open Windows popup.
        with mock.patch.object(self.app.help_menu,'entryconfigure',wraps=self.app.help_menu.entryconfigure) as configure:
            for _ in range(20):
                self.window.after_cancel(self.app.poll_id)
                self.app.poll()
        configure.assert_not_called()
    def test_help_menu_updates_once_per_busy_or_backup_change(self):
        self.app.backup_available=True;self.app.controls()
        self.assertEqual(self.app.help_menu.entrycget(4,'state'),'normal')
        self.controller.busy=True;self.controller.started=time.monotonic()
        with mock.patch.object(self.app.help_menu,'entryconfigure',wraps=self.app.help_menu.entryconfigure) as configure:
            self.app.controls();self.assertEqual(configure.call_count,3)
            for index in (1,3,4):self.assertEqual(self.app.help_menu.entrycget(index,'state'),'disabled')
            configure.reset_mock()
            for _ in range(20):self.app.controls()
            configure.assert_not_called()
            self.controller.busy=False;self.app.controls();self.assertEqual(configure.call_count,3)
            for index in (1,3,4):self.assertEqual(self.app.help_menu.entrycget(index,'state'),'normal')
            configure.reset_mock();self.app.backup_available=False;self.app.controls()
            self.assertEqual(configure.call_count,1);self.assertEqual(self.app.help_menu.entrycget(4,'state'),'disabled')
    def test_worker_permission_retry_preserves_original_request(self):
        self.app.last_request=dict(operation='predict',sex='men',fighter_a='A',fighter_b='B')
        with mock.patch.object(self.gui.messagebox,'askyesno',return_value=True):
            self.app.handle_terminal(dict(type='error',code='worker_permission',message='blocked',log='test.log'))
        self.assertEqual(self.controller.request,dict(self.app.last_request,workers=1))

if __name__=='__main__':unittest.main()

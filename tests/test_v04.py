"""Outcome, durable-error, progress and frozen recent-history contracts."""
import copy
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import test_safety as safety
import analyzer_maintenance as maintenance
from analyzer_errors import MaintenanceError, diagnostic_text
from analyzer_protocol import EventReader, validated_progress, MAX_RECORD_BYTES
from analyzer_runtime import run_logged_process
from analyzer_fight_history import recent_fights, format_recent_fights, OLD_HISTORY_MESSAGE
from analyzer_history import History
from analyzer_reporting import format_html
from analyzer_results import format_result
from test_gui import result, FakeController

def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or list(rows[0]));writer.writeheader();writer.writerows(rows)

class CompletedResultContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        safety.UpdaterAuditTests.setUpClass();cls.fixture=safety.UpdaterAuditTests()
        cls.men=cls.fixture.modules['men'];cls.pd=cls.fixture.pd

    def fight(self,outcome='win_loss'):
        return dict(fight_id='new',result=outcome,fighter_red_id='a',fighter_blue_id='b',winner_id='a' if outcome=='win_loss' else '',loser_id='b' if outcome=='win_loss' else '',event_date='2020-01-01')

    def audit(self,rows,fight):
        return self.men.audit_new_rows_for_apply(self.pd.DataFrame([fight]),rows,set(),self.pd.Timestamp('2026-10-11'),False)

    def test_completed_pairs_accept_both_orders_and_nonbinary(self):
        event=dict(event_name='Example',event_date='2020-01-01')
        for markers,outcome in [(['W','L'],'win_loss'),(['L','W'],'win_loss'),(['D','D'],'draw'),(['N/C','NC'],'no_contest')]:
            with self.subTest(markers=markers):
                meta=dict(fighter_1='A',fighter_2='B',fighter_1_result_marker=markers[0],fighter_2_result_marker=markers[1])
                self.men.validate_completed_fight_meta(meta,event,self.pd.Timestamp('2026-10-11'),False)
                rows=self.fixture.rows();fight=self.fight(outcome)
                if outcome!='win_loss':rows['result']=outcome;rows['won']=float('nan')
                elif markers[0]=='L':
                    rows['result']=['loss','win'];rows['won']=[0,1];fight.update(winner_id='b',loser_id='a')
                self.men.validate_parsed_result(meta,fight,rows.to_dict('records'),self.pd.Timestamp('2026-10-11'))
                self.assertEqual(self.audit(rows,fight)['unsafe_rows_count'],0)

    def test_contradictions_and_nonbinary_targets_are_blocked(self):
        event=dict(event_name='Example',event_date='2020-01-01')
        for markers in [('W','W'),('L','L'),('D','L'),('NC','D'),('NC','')]:
            meta=dict(fighter_1='A',fighter_2='B',fighter_1_result_marker=markers[0],fighter_2_result_marker=markers[1])
            with self.subTest(markers=markers),self.assertRaises(self.men.SkippedFight):self.men.validate_completed_fight_meta(meta,event,self.pd.Timestamp('2026-10-11'),False)
        for outcome in ('draw','no_contest'):
            rows=self.fixture.rows();rows['result']=outcome
            self.assertGreater(self.audit(rows,self.fight(outcome))['unsafe_rows_count'],0)
            rows['won']=float('nan');fight=self.fight(outcome);fight['winner_id']='a'
            self.assertGreater(self.audit(rows,fight)['unsafe_rows_count'],0)

    def test_identity_target_date_and_orphan_metadata_are_blocked(self):
        for column,value in [('fighter_id',None),('fighter_name',None),('opponent_id','wrong'),('won',0),('event_date','2020-01-02')]:
            rows=self.fixture.rows();rows.loc[0,column]=value
            with self.subTest(column=column):self.assertGreater(self.audit(rows,self.fight())['unsafe_rows_count'],0)
        self.assertGreater(self.audit(self.fixture.rows().iloc[:0],self.fight())['unsafe_rows_count'],0)

    def test_metadata_requires_valid_date_and_distinct_fighter_identity(self):
        for sex,module in self.fixture.modules.items():
            for invalid_date,same_name in [(True,False),(False,True)]:
                event=dict(event_name='Example',event_date=None if invalid_date else '2020-01-01')
                with self.subTest(sex=sex,date=invalid_date),self.assertRaises(module.SkippedFight):
                    if sex=='men':module.validate_completed_fight_meta(dict(fighter_1='A',fighter_2='A' if same_name else 'B',fighter_1_result_marker='D',fighter_2_result_marker='D'),event,self.pd.Timestamp('2026-10-11'),False)
                    else:module.validate_completed_people([dict(fighter='A',result_marker='D'),dict(fighter='A' if same_name else 'B',result_marker='D')],event,self.pd.Timestamp('2026-10-11'),False)

    def test_men_duplicate_names_and_aliases_use_source_ids(self):
        meta=dict(fighter_1='Same Name',fighter_2='Same Name',fighter_1_profile_url='http://ufcstats.com/fighter-details/a',fighter_2_profile_url='http://ufcstats.com/fighter-details/b',fighter_1_result_marker='W',fighter_2_result_marker='L')
        event=dict(event_name='Example',event_date='2020-01-01');today=self.pd.Timestamp('2026-10-11')
        self.men.validate_completed_fight_meta(meta,event,today,False)
        rows=self.fixture.rows();rows['fighter_name']='Same Name'
        self.men.validate_parsed_result(meta,self.fight(),rows.to_dict('records'),today)
        rows['fighter_name']=['Earlier Name A','Earlier Name B']
        self.men.validate_parsed_result(meta,self.fight(),rows.to_dict('records'),today)
        meta['fighter_2_profile_url']=meta['fighter_1_profile_url']
        with self.assertRaises(self.men.SkippedFight):self.men.validate_completed_fight_meta(meta,event,today,False)

class MaintenanceErrorContracts(unittest.TestCase):
    def attempt(self, root, status='fight_fetch_error'):
        safety.mini_root(root)
        def runner(cmd,cwd,log):
            audit=cwd/'_update_manifests/run';audit.mkdir(parents=True)
            (audit/'new_rows_safety_audit.json').write_text('{"unsafe_rows_count":0}')
            write_csv(audit/'fights_inspected.csv',[dict(status=status,fight_id='bout',event_name='Event',fighter_1='A',fighter_2='B')])
        return maintenance.maintenance(root,target='men',apply=True,runner=runner)

    def test_bout_error_resolves_to_retained_file_after_stage_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(MaintenanceError) as context:self.attempt(root)
            error=context.exception
            self.assertEqual((error.code,error.retryable,error.installation_state),('source_fetch_failed',True,'unchanged'))
            self.assertEqual((error.event_name,error.fighter_a,error.fight_id),('Event','A','bout'))
            self.assertTrue(Path(error.diagnostics_path).is_file())
            self.assertIn('audits',Path(error.diagnostics_path).parts)
            self.assertFalse((root/'.runtime/transactions'/error.transaction_id/'stage').exists())

    def test_invalid_result_never_offers_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(MaintenanceError) as context:self.attempt(Path(temp),'skipped_no_winner_loser')
            self.assertEqual(context.exception.code,'invalid_source_result');self.assertFalse(context.exception.retryable)

    def test_cleanup_failure_does_not_mask_original_error(self):
        real_copy=maintenance.shutil.copytree
        def copy(src,dst,*args,**kwargs):
            if Path(src).name=='_update_manifests':raise OSError('audit copy failed')
            return real_copy(src,dst,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(maintenance.shutil,'copytree',side_effect=copy):
            with self.assertRaises(MaintenanceError) as context:self.attempt(Path(temp))
            self.assertEqual(context.exception.code,'source_fetch_failed')
            self.assertEqual(Path(context.exception.diagnostics_path).name,'failure.log')
            self.assertTrue(Path(context.exception.diagnostics_path).is_file())

    def test_recovery_failure_is_truthful_and_retained(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(maintenance,'rollback',side_effect=OSError('backup inaccessible')):
            with self.assertRaises(MaintenanceError) as context:self.attempt(Path(temp))
            error=context.exception;self.assertEqual(error.code,'recovery_failed');self.assertEqual(error.installation_state,'recovery_required')
            path=Path(temp)/'.runtime/transactions'/error.transaction_id/'journal.json'
            self.assertEqual(json.loads(path.read_text())['status'],'recovery_required')
            self.assertTrue(Path(error.diagnostics_path).is_file())

    def test_diagnostic_copy_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'log';path.write_text('x'*10000+'\n'+str(Path('C:/Users')/'SomeAccount'/'private.log')+'\ntoken=privatevalue\nhttps://user:password@example.com\nAuthorization: Bearer bearer-value\nProxy-Authorization=Basic basic-value\n{"Authorization": "Bearer json-value"}',encoding='utf-8')
            text=diagnostic_text(dict(code='failed',diagnostics_path=str(path)),'0.4.0')
            self.assertLess(len(text),6200)
            for value in ('SomeAccount','privatevalue','user:password','bearer-value','basic-value','json-value'):self.assertNotIn(value,text)

class ProgressContracts(unittest.TestCase):
    def test_partial_unicode_bad_and_oversized_records(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'events';reader=EventReader(path)
            raw=json.dumps(dict(type='progress',stage='download',message='José'),ensure_ascii=False).encode()
            position=raw.index('é'.encode())+1;path.write_bytes(raw[:position]);self.assertEqual(reader.read(),[])
            with path.open('ab') as stream:stream.write(raw[position:]+b'\ninvalid\n'+b'x'*(MAX_RECORD_BYTES*2)+b'\n'+raw+b'\n')
            self.assertEqual([r['message'] for r in reader.read()],['José','José'])

    def test_children_cannot_supply_terminal_or_worker_identity(self):
        self.assertIsNone(validated_progress(dict(type='result',payload={'status':'committed'})))
        self.assertIsNone(validated_progress(dict(type='progress',stage='committing',message='Forged commit',cancellable=True)))
        record=validated_progress(dict(type='progress',message='Checking',completed=2,total=4,unit='bouts',job_id='forged',cancellable=False))
        self.assertNotIn('job_id',record);self.assertTrue(record['cancellable']);self.assertEqual(record['unit'],'bouts')
        for total in (-1,'4',0):self.assertNotIn('total',validated_progress(dict(message='Checking',completed=1,total=total)))

    def test_real_child_final_event_is_drained_separate_from_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'child.py'
            script.write_text("import os,json\nfrom pathlib import Path\nprint('human log')\nPath(os.environ['UFC_ENGINE_EVENTS']).write_text(json.dumps(dict(type='progress',stage='download',message='Final bout',completed=3,total=3,unit='bouts'))+'\\n')\n",encoding='utf-8')
            events=[];run_logged_process([sys.executable,str(script)],root,root/'child.log',progress=lambda **r:events.append(r))
            self.assertEqual(events[-1]['completed'],3);self.assertIn('human log',(root/'child.log').read_text())

    def test_summary_reconciles_fights_and_binary_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base=root/'_update_manifests/run'
            rows=[dict(fight_id=str(i),status='scraped',outcome=outcome,event_date='2020-01-01',training_eligible=outcome=='win_loss') for i,outcome in enumerate(('win_loss','draw','nc'))]
            write_csv(base/'fights_inspected.csv',rows);write_csv(base/'events_inspected.csv',[dict(status='ok')])
            fights,summary=maintenance.captured_fights(root)
            self.assertEqual(len(fights),3)
            self.assertEqual([summary[k] for k in ('events_inspected','captured_fights','decisive_fights','draws','no_contests','proposed_binary_training_rows')],[1,3,1,1,1,2])

class RecentHistoryContracts(unittest.TestCase):
    def fixture(self, root, sex):
        rows=[]
        for i,outcome in enumerate(('win','loss','draw','no_contest','win','loss','win')):
            rows.append(dict(fight_id=str(i),event_id=str(i),event_date=f'2020-01-{i+1:02d}',fighter_red_id='a',fighter_blue_id='b',winner_id='a' if outcome=='win' else 'b' if outcome=='loss' else '',loser_id='b' if outcome=='win' else 'a' if outcome=='loss' else '',result='win_loss' if outcome in ('win','loss') else outcome,weight_class='Lightweight' if i%2 else 'Welterweight',method='KO <tag>',round='1',time='1:00'))
        if sex=='men':
            base=root/'mens_ufc_model/data/raw/ufcstats_men'
            write_csv(base/'fights.csv',rows+[rows[0]])
            write_csv(base/'fighters.csv',[dict(fighter_id='a',fighter_name='José'),dict(fighter_id='b',fighter_name='Opponent')])
            write_csv(base/'events.csv',[dict(event_id=str(i),event_name='Event '+str(i)) for i in range(7)])
            write_csv(base/'fight_stats.csv',[dict(fight_id=str(i),fighter_id='a',fighter_name='José',opponent_name='Opponent') for i in range(7)])
        else:
            women=[]
            for row in rows:
                for name,identity,opponent in [('José','a','Opponent'),('Opponent','b','José')]:
                    outcome='draw' if row['result']=='draw' else 'nc' if row['result']=='no_contest' else 'win' if row['winner_id']==identity else 'loss'
                    women.append(dict(fight_id=row['fight_id'],event_date=row['event_date'],event_name='Event '+row['fight_id'],fighter=name,profile_url='http://example/'+identity,opponent=opponent,result=outcome,division=row['weight_class'],method=row['method'],round=row['round'],time=row['time']))
            write_csv(root/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv',women+[women[0]])

    def test_strict_cutoff_dedup_five_nonbinary_cross_division_and_swap(self):
        for sex in ('men','women'):
            with self.subTest(sex=sex),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.fixture(root,sex)
                history=recent_fights(root,sex,('José','a'),('Opponent','b'),'2020-01-07')
                self.assertEqual([r['fight_id'] for r in history['fighter_a']],['5','4','3','2','1'])
                self.assertEqual(len({r['division'] for r in history['fighter_a']}),2)
                self.assertTrue(any(r['result']=='draw' for r in history['fighter_a']))
                self.assertTrue(any(r['result'] in ('nc','no_contest') for r in history['fighter_a']))
                swapped=recent_fights(root,sex,('Opponent','b'),('José','a'),'2020-01-07')
                self.assertEqual(swapped['fighter_b'],history['fighter_a'])
                self.assertEqual(recent_fights(root,sex,('José','a'),('Opponent','b'),'2020-01-01')['fighter_a'],[])

    def test_exports_history_and_all_preview_states_use_frozen_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,'men')
            payload=dict(result(),result_state='complete',generated_at='2026-10-11T10:00:00+00:00',recent_fights=recent_fights(root,'men',('José','a'),('Opponent','b'),'2020-01-07'))
            original=copy.deepcopy(payload)
            for state in ('complete','comparison','pending','failed','cancelled'):
                value=dict(payload,result_state=state)
                self.assertIn('No contest',format_result(value));self.assertIn('KO &lt;tag&gt;',format_html(value));self.assertNotIn('<tag>',format_html(value))
            history=History(root);identifier=history.save({'operation':'compare','sex':'men'},{'version':'original'},payload)
            (root/'mens_ufc_model/data/raw/ufcstats_men/fights.csv').unlink()
            self.assertEqual(next(e for e in history.entries() if e['id']==identifier)['payload']['recent_fights'],original['recent_fights'])
            self.assertEqual(payload,original)
            self.assertIn(OLD_HISTORY_MESSAGE,format_recent_fights(result()))

    def test_women_alias_uses_validated_profile_identity_and_opponent_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,'women')
            path=root/'womens_ufc_model/output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv'
            with path.open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
            for row in rows:
                if row['fight_id']=='2' and row['fighter']=='José':row['fighter']='Earlier Name'
            write_csv(path,rows)
            history=recent_fights(root,'women',('José','a'),('Opponent','b'),'2020-01-07')
            draw=next(r for r in history['fighter_a'] if r['fight_id']=='2')
            self.assertEqual(draw['result'],'draw');self.assertEqual(draw['opponent_id'],'b')

@unittest.skipUnless(os.name=='nt','Native Windows layout check')
class RecentWindowContracts(unittest.TestCase):
    def test_error_actions_preserve_report_and_retry_starts_fresh_request(self):
        import tkinter as tk
        from tkinter import ttk
        from analyzer_gui import AnalyzerApp
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);window=tk.Tk();app=AnalyzerApp(window,root,FakeController(),False)
            try:
                app.display_result(result());original=app.result_text;app.last_request={'operation':'update','max_events':1}
                log=root/'retained.log';log.write_text('Diagnostic excerpt')
                error=MaintenanceError('source_fetch_failed','Download failed','Request failed',retryable=True,diagnostics_path=str(log)).payload()
                app.handle_terminal(dict(type='error',code=error['code'],message=error['message'],log=str(log),maintenance_error=error))
                dialog=next(w for w in window.winfo_children() if isinstance(w,tk.Toplevel))
                buttons={w.cget('text'):w for frame in dialog.winfo_children() for w in frame.winfo_children() if isinstance(w,ttk.Button)}
                self.assertEqual(set(buttons),{'Retry','View details','Copy diagnostics','Close'})
                buttons['Copy diagnostics'].invoke();self.assertIn('source_fetch_failed',window.clipboard_get())
                with mock.patch('analyzer_gui.os.startfile') as opened:buttons['View details'].invoke();opened.assert_called_once_with(log)
                with mock.patch.object(app,'start') as start:
                    buttons['Retry'].invoke();window.update();start.assert_called_once_with({'operation':'update','max_events':1})
                self.assertEqual(app.result_text,original);self.assertEqual(str(app.save_button.cget('state')),'normal')
            finally:app.destroy()

    def test_recovery_error_disables_analysis_and_has_no_retry(self):
        import tkinter as tk
        from tkinter import ttk
        from analyzer_gui import AnalyzerApp
        with tempfile.TemporaryDirectory() as temp:
            window=tk.Tk();app=AnalyzerApp(window,Path(temp),FakeController(),False);app.ready=True
            try:
                app.maintenance_error_dialog(dict(maintenance_error=MaintenanceError('recovery_failed','Recovery failed','Restore failed',installation_state='recovery_required',retryable=True).payload()))
                dialog=next(w for w in window.winfo_children() if isinstance(w,tk.Toplevel))
                buttons=[w.cget('text') for frame in dialog.winfo_children() for w in frame.winfo_children() if isinstance(w,ttk.Button)]
                self.assertNotIn('Retry',buttons);self.assertFalse(app.ready)
                dialog.event_generate('<Escape>');window.update()
            finally:app.destroy()

    def test_current_phase_bar_switches_between_known_and_unknown_totals(self):
        import tkinter as tk
        from analyzer_gui import AnalyzerApp
        with tempfile.TemporaryDirectory() as temp:
            window=tk.Tk();controller=FakeController();app=AnalyzerApp(window,Path(temp),controller,False)
            try:
                controller.start({'operation':'update'})
                app.pending_stage=dict(stage='download',phase='bouts',total=12,completed=8,unit='bouts');app.controls()
                self.assertEqual(str(app.progress.cget('mode')),'determinate');self.assertEqual(float(app.progress.cget('value')),8)
                app.pending_stage=dict(stage='rebuilding',phase='steps',step_index=2,step_count=4);app.controls()
                self.assertEqual(str(app.progress.cget('mode')),'indeterminate')
                controller.busy=False;app.controls();self.assertEqual(float(app.progress.cget('value')),0)
            finally:app.destroy()

    def test_native_recent_table_frozen_labels_large_and_narrow_layout(self):
        import tkinter as tk
        from analyzer_gui import AnalyzerApp
        with tempfile.TemporaryDirectory() as temp:
            window=tk.Tk();controller=FakeController()
            app=AnalyzerApp(window,Path(temp),controller,False)
            try:
                payload=dict(result(),recent_fights=dict(schema_version=1,history_cutoff='2026-10-10',fighter_a=[dict(fight_id='x',event_date='2020-01-01',opponent='Other Fighter',result='draw',division='Lightweight',method='DEC',event_name='Example',round='3',time='5:00')],fighter_b=[]))
                app.display_result(payload);self.assertEqual(app.recent_trees['fighter_a'].item('0')['values'][2],'Draw')
                app.names['a'].set('Changed');self.assertIn(payload['fighter_a'],app.recent_titles['fighter_a'].get())
                window.geometry('720x620');app.font_size.set('Large');app.change_font();window.update();app.layout_recent()
                self.assertEqual(app.recent_groups['fighter_b'].grid_info()['row'],1)
                app.display_result(result());self.assertEqual(app.recent_caption.get(),OLD_HISTORY_MESSAGE)
            finally:app.destroy()

"""Behavioral coverage for dated comparisons, history safety and the native UI."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from analyzer_catalog import FighterCatalog, IdentityError
from analyzer_history import History, fingerprint
from analyzer_reporting import report_sections, overview_rows, format_html
from analyzer_results import format_result, result_filename
from analyzer_widgets import CalendarDialog
from test_gui import catalogue_fixture, result, FakeController
from test_safety import mini_root

def mini_gui_root(root):
    mini_root(root)
    catalogue_fixture(root)

def sample(state='complete'):
    value=dict(result(),result_state=state,generated_at='2026-10-01T10:00:00+00:00')
    value['fighter_a_comparison']=dict(age_at_fight=30,reach_cm=180,elo_before=1600,division_elo_before=1500,fights_in_division_before=0,career_sapm_before=0)
    value['fighter_b_comparison']=dict(age_at_fight=32,reach_cm=175,elo_before=1550,division_elo_before=1510,fights_in_division_before=1,career_sapm_before=None)
    if state!='complete':
        for field in ('fighter_a_win_probability','fighter_b_win_probability','predicted_winner','confidence_tier'):value.pop(field,None)
    return value

class ReportingTests(unittest.TestCase):
    def test_partial_comparison_never_fabricates_prediction(self):
        for state in ('comparison','pending','cancelled','failed'):
            value=sample(state);text=format_result(value)
            self.assertNotIn('Predicted winner:',text);self.assertNotIn('Confidence:',text)
            self.assertIn('Overall Elo',text)
            self.assertIn('statistics only',result_filename(value))

    def test_preview_final_structured_metrics_are_identical(self):
        self.assertEqual(report_sections(sample()),report_sections(sample('pending')))
        self.assertEqual(len(overview_rows(sample())),12)

    def test_zero_missing_baseline_units_and_direction(self):
        rows={r['label']:r for s in report_sections(sample()) for r in s['rows']}
        self.assertEqual(rows['Sig. strikes absorbed / min']['a'],'0.00')
        self.assertEqual(rows['Sig. strikes absorbed / min']['b'],'N/A')
        self.assertEqual(rows['Sig. strikes absorbed / min']['direction'],'Lower generally favorable')
        self.assertTrue(rows['Division Elo']['support_notes'])
        self.assertEqual(rows['Age (years)']['direction'],'Context dependent')

    def test_html_is_escaped_offline_and_complete(self):
        value=sample();value['fighter_a']='<script>alert("x")</script>'
        html=format_html(value)
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('src=',html);self.assertNotIn('href=',html)
        self.assertIn('MODEL DETAILS',html);self.assertIn('Limited history',html)

    def test_report_does_not_mutate_result(self):
        value=sample();original=copy.deepcopy(value)
        format_html(value);report_sections(value);overview_rows(value)
        self.assertEqual(value,original)

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.history=History(self.root)
        self.request=dict(operation='predict',sex='men',fighter_a='A',fighter_b='B',workers='automatic',fight_date='2026-10-10',division='Lightweight')
        self.context=dict(data='hash1',code='code1',runtime='version1')
    def tearDown(self):self.temp.cleanup()

    def test_exact_reuse_and_all_settings_invalidation(self):
        self.history.save(self.request,self.context,sample())
        self.assertIsNotNone(self.history.lookup(self.request,self.context))
        for field in self.request:
            changed=dict(self.request);changed[field]='different'
            self.assertIsNone(self.history.lookup(changed,self.context))
        for field in self.context:
            changed=dict(self.context);changed[field]='different'
            self.assertIsNone(self.history.lookup(self.request,changed))

    def test_failures_previews_and_cancellations_are_not_stored(self):
        for state in ('pending','cancelled','failed'):self.assertIsNone(self.history.save(self.request,self.context,sample(state)))
        self.assertFalse(self.history.entries())
        self.history.save(dict(self.request,operation='compare'),self.context,sample('comparison'))
        self.assertEqual(len(self.history.entries()),1)

    def test_recalculation_replaces_identical_entry_without_duplicates(self):
        self.history.save(self.request,self.context,sample());self.history.save(self.request,self.context,sample())
        self.assertEqual(len(self.history.entries()),1)

    def test_corrupt_unsupported_and_tampered_entries_are_skipped(self):
        identifier=self.history.save(self.request,self.context,sample());path=self.history.directory/(identifier+'.json')
        entry=json.loads(path.read_text());entry['payload']['fighter_a']='tampered';path.write_text(json.dumps(entry))
        (self.history.directory/'broken.json').write_text('{broken')
        (self.history.directory/'future.json').write_text('{"schema":999}')
        self.assertEqual(self.history.entries(),[])

    def test_failed_atomic_replacement_keeps_previous_analysis(self):
        identifier=self.history.save(self.request,self.context,sample())
        with mock.patch('analyzer_history.atomic_json',side_effect=OSError('Storage unavailable')):
            with self.assertRaises(OSError):self.history.save(self.request,self.context,sample())
        self.assertEqual(self.history.lookup(self.request,self.context)['id'],identifier)

    def test_incomplete_and_non_object_history_do_not_break_startup(self):
        self.history.directory.mkdir(parents=True)
        (self.history.directory/'list.json').write_text('[]')
        identifier='0'*32
        entry=dict(schema=1,id=identifier,payload={})
        entry['integrity']=fingerprint(entry)
        (self.history.directory/(identifier+'.json')).write_text(json.dumps(entry))
        self.assertEqual(self.history.entries(),[])

    def test_count_and_size_bounds_delete_and_clear(self):
        with mock.patch('analyzer_history.MAX_ENTRIES',3):
            for i in range(5):self.history.save(dict(self.request,division=str(i)),self.context,sample())
        self.assertEqual(len(self.history.entries()),3)
        self.history.delete(self.history.entries()[0]['id']);self.assertEqual(len(self.history.entries()),2)
        with self.assertRaises(ValueError):self.history.delete('../outside')
        with mock.patch('analyzer_history.MAX_BYTES',1):self.history.prune()
        self.assertFalse(self.history.entries());self.history.clear()

class CoverageTests(unittest.TestCase):
    def test_dates_filter_same_day_future_and_divisions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);mini_gui_root(root)
            (root/'mens_ufc_model/data/raw/ufcstats_men/fights.csv').write_text('fight_id,event_date,weight_class,fighter_red_id,fighter_blue_id\n1,2020-01-01,Lightweight,a,b\n2,2021-01-01,Welterweight,a,b\n3,2022-01-01,Lightweight,a,b\n')
            catalog=FighterCatalog('men',root);coverage=catalog.coverage(('José Alpha','a'),'2021-01-01','Lightweight')
            self.assertEqual(coverage['fights'],1);self.assertEqual(coverage['latest'],'2020-01-01');self.assertEqual(coverage['division_fights'],1)
            description=catalog.suggestion_description(('José Alpha','a'),'2021-01-01','Lightweight')
            self.assertIn('2020-01-01',description);self.assertNotIn('2022-01-01',description)
            self.assertEqual(catalog.coverage(('José Alpha','a'),'2019-01-01','Lightweight')['fights'],0)
            self.assertEqual(FighterCatalog.from_payload(catalog.to_payload()).coverage(('José Alpha','a'),'2021-01-01','Lightweight'),coverage)
            with self.assertRaises(IdentityError) as error:catalog.resolve('zzzzzzzzzz')
            self.assertEqual(error.exception.candidates,[])

class ProtocolTests(unittest.TestCase):
    def test_nonterminal_comparison_and_obsolete_messages(self):
        from analyzer_controller import WorkerController
        with tempfile.TemporaryDirectory() as temp:
            controller=WorkerController(Path(temp));controller.finished=False;controller.cancel_requested=False
            controller.process=mock.Mock();controller.process.poll.return_value=None
            controller.job_id='current';controller.request_fingerprint='request'
            controller.events_path=Path(temp)/'events.jsonl'
            rows=[dict(type='result',job_id='obsolete',request_fingerprint='old',payload={}),
                  dict(type='comparison_ready',job_id='current',request_fingerprint='request',payload=sample('pending')),
                  dict(type='progress',job_id='current',request_fingerprint='request',stage='training',message='Fitting',cancellable=True)]
            controller.events_path.write_text('\n'.join(json.dumps(row) for row in rows)+'\n',encoding='utf-8')
            received=controller.poll()
            self.assertEqual([row['type'] for row in received],['comparison_ready','progress'])
            self.assertFalse(controller.terminal);self.assertTrue(controller.busy);self.assertTrue(controller.cancellable)

    def test_cache_flags_are_mutually_exclusive_for_both_commands(self):
        from ufc_matchup_analyzer import parser
        import contextlib,io
        for operation in ('predict','compare'):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parser().parse_args([operation,'men','--fighter-a','A','--fighter-b','B','--division','Lightweight','--fight-date','2026-10-10','--use-cache','--force-recalculate'])

class EnhancedWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name!='nt' and not os.environ.get('DISPLAY'):raise unittest.SkipTest('Native window checks require a graphical display')
    def setUp(self):
        from analyzer_gui import AnalyzerApp,tk
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);mini_gui_root(self.root)
        self.window=tk.Tk();self.controller=FakeController();self.app=AnalyzerApp(self.window,self.root,self.controller,False)
        self.app.catalogs={sex:FighterCatalog(sex,self.root) for sex in ('men','women')};self.app.ready=True;self.window.update();self.app.controls()
    def tearDown(self):self.app.destroy();self.temp.cleanup()

    def existing_analysis(self,state='complete'):
        self.app.names['a'].set('José Alpha');self.app.names['b'].set('Other Fighter');self.app.date.set('2026-10-10')
        request=self.app.prediction_request()
        import datetime as dt
        payload=sample(state)
        payload.update(fight_date=request['fight_date'],calculation_fingerprint='verified')
        cutoff=(dt.date.fromisoformat(request['fight_date'])-dt.timedelta(days=1)).isoformat() if request['fight_date']<=dt.date.today().isoformat() else dt.date.today().isoformat()
        payload['calculation_request']=dict(request,operation='predict' if state=='complete' else 'compare',as_of_date=None,effective_cutoff=cutoff,workers='automatic')
        self.app.history_contexts={'men':'verified'};self.app.display_result(payload)
        return payload

    def test_compare_opens_existing_prediction_without_a_worker_or_history_write(self):
        import copy
        payload=self.existing_analysis();before=copy.deepcopy(payload);text=self.app.result_text
        self.app.history_setting.set(False)
        with mock.patch.object(self.controller,'start') as start,mock.patch.object(self.app.history,'save') as save:
            self.app.compare();self.window.update()
        start.assert_not_called();save.assert_not_called()
        self.assertEqual(self.app.notebook.select(),str(self.app.comparison))
        self.assertEqual(self.app.result,before);self.assertEqual(self.app.result_text,text)
        self.assertIn('No datasets reloaded',self.app.status.get());self.assertFalse(self.controller.busy)
        self.app.copy();self.window.update();self.assertEqual(self.window.clipboard_get(),text)

    def test_repeated_statistics_button_opens_existing_comparison(self):
        self.existing_analysis('comparison')
        with mock.patch.object(self.controller,'start') as start:
            self.app.compare();self.app.compare()
        start.assert_not_called();self.assertEqual(self.app.result['result_state'],'comparison')

    def test_changed_or_outdated_comparisons_start_a_new_job(self):
        changes=[('fighter_a','Same Name'),('fight_date','2026-10-11'),('division','Welterweight'),('fighter_a_id','different'),('as_of_date','2025-01-01'),('effective_cutoff','2000-01-01'),('sex','women')]
        for field,value in changes:
            with self.subTest(field=field):
                self.controller.busy=False;payload=self.existing_analysis()
                payload['calculation_request'][field]=value
                self.app.compare();self.assertTrue(self.controller.busy)
        for state in ('pending','cancelled','failed'):
            with self.subTest(state=state):
                self.controller.busy=False;payload=self.existing_analysis(state)
                self.app.compare();self.assertTrue(self.controller.busy)
        self.controller.busy=False;payload=self.existing_analysis();self.app.history_contexts['men']='updated datasets'
        self.app.compare();self.assertTrue(self.controller.busy)

    def test_statistics_navigation_does_not_derive_reversed_values(self):
        self.existing_analysis();self.app.swap()
        self.app.compare();self.assertTrue(self.controller.busy)
        self.assertEqual(self.controller.request['fighter_a'],'Other Fighter')

    def test_missing_metrics_or_manual_profiles_require_preparation(self):
        for missing in ('fighter_a_comparison','calculation_fingerprint','calculation_request'):
            with self.subTest(missing=missing):
                self.controller.busy=False;payload=self.existing_analysis();payload.pop(missing)
                self.app.compare();self.assertTrue(self.controller.busy)
        self.controller.busy=False;payload=self.existing_analysis();payload['calculation_request']['profiles_sha256']='manual'
        self.app.compare();self.assertTrue(self.controller.busy)

    def test_recalculate_still_starts_an_explicit_fresh_job(self):
        self.existing_analysis();self.app.recalculate()
        self.assertTrue(self.controller.busy);self.assertTrue(self.controller.request['force_recalculate'])
        self.assertFalse(self.controller.request['use_cache'])

    def test_tabs_filter_and_full_copy_remain_complete(self):
        self.app.display_result(sample());self.assertEqual(len(self.app.notebook.tabs()),3)
        original=self.app.result_text;self.app.filter.set('Elo');self.app.copy();self.window.update()
        self.assertEqual(self.window.clipboard_get(),original)
        self.assertEqual(len(self.app.comparison_tree.get_children()),2)

    def test_inline_invalid_date_and_stale_result(self):
        self.app.display_result(sample());self.app.date.set('2025-02-29')
        with self.assertRaises(Exception):self.app.prediction_request()
        self.assertTrue(self.app.errors['date'].get());self.assertIn('previous matchup',self.app.stale.get())
        self.assertFalse(self.controller.busy)

    def test_swap_and_category_names(self):
        self.app.names['a'].set('José Alpha');self.app.names['b'].set('Other Fighter');self.app.swap()
        self.assertEqual(self.app.names['a'].get(),'Other Fighter')
        self.app.division.set('Women — Flyweight');self.app.change_division();self.assertEqual(self.app.names['a'].get(),'')
        self.app.division.set('Men — Lightweight');self.app.change_division();self.assertEqual(self.app.names['a'].get(),'Other Fighter')

    def test_calendar_leap_month_navigation_and_keyboard_focus(self):
        picker=CalendarDialog(self.window,'2024-02-29',self.app.date.set)
        self.window.update();self.assertEqual(len(picker.buttons),29);picker.move(1);self.assertEqual(picker.date.month,3);picker.move(-1);self.assertEqual(len(picker.buttons),29);picker.window.destroy()

    def test_background_history_view_is_not_replaced_on_completion(self):
        self.app.display_result(sample());self.app.viewing_other=True
        new=dict(sample(),fighter_a='New Fighter')
        self.app.handle_terminal(dict(type='result',operation='predict',payload=new))
        self.assertEqual(self.app.result['fighter_a'],'José Alpha');self.app.open_new();self.assertEqual(self.app.result['fighter_a'],'New Fighter')

    def test_html_save_and_statistics_filename(self):
        self.app.display_result(sample('comparison'));dest=self.root/'report.html'
        from analyzer_gui import filedialog
        with mock.patch.object(filedialog,'asksaveasfilename',return_value=str(dest)):self.app.save()
        self.assertIn('<table>',dest.read_text());self.assertIn('statistics only',result_filename(self.app.result))

    def test_metric_help_font_sizes_and_restore_unavailable(self):
        self.app.display_result(sample());item=self.app.comparison_tree.get_children()[0]
        self.app.comparison_tree.selection_set(item);self.app.metric_details(self.app.comparison_tree)
        self.assertIn('Profile measurement',self.app.details.get('1.0','end'))
        self.app.font_size.set('Large');self.app.change_font();self.assertIn('12',str(self.app.output['font']))
        self.app.controls();self.assertEqual(self.app.help_menu.entrycget(4,'state'),'disabled')

    def test_history_preference_persists_without_deleting_results(self):
        self.app.history.save(dict(operation='predict',sex='men'),{},sample())
        self.app.history_setting.set(False);self.app.save_history_setting()
        self.assertFalse(json.loads(self.app.preferences_path.read_text())['history_enabled']);self.assertEqual(len(self.app.history.entries()),1)

    def test_unknown_name_error_is_inline_and_does_not_start(self):
        self.app.names['a'].set('zzzzzzzzzz');self.app.names['b'].set('Other Fighter')
        self.app.analyze();self.assertIn('not found',self.app.errors['a'].get());self.assertFalse(self.controller.busy)

    def test_training_failure_retains_comparison_and_does_not_save_history(self):
        self.app.last_request=dict(operation='predict');self.app.preview=sample('pending');self.app.display_result(self.app.preview)
        from analyzer_gui import messagebox
        with mock.patch.object(messagebox,'showerror'):
            self.app.handle_terminal(dict(type='error',code='failed',message='Training failed',log='log'))
        self.assertEqual(self.app.result['result_state'],'failed')
        self.assertEqual(report_sections(self.app.result),report_sections(sample('pending')))
        self.assertFalse(self.app.history.entries());self.assertIn('failed',self.app.result_text)

    def test_maintenance_failure_preserves_successful_result(self):
        self.app.display_result(sample());self.app.preview=sample('pending');self.app.last_request=dict(operation='update')
        from analyzer_gui import messagebox
        with mock.patch.object(messagebox,'showerror'):
            self.app.handle_terminal(dict(type='error',code='failed',message='Network failed',log='log'))
        self.assertEqual(self.app.result['result_state'],'complete')

    def test_cancelled_preview_is_available_while_viewing_another_analysis(self):
        self.app.display_result(sample());self.app.last_request=dict(operation='predict')
        self.app.preview=sample('pending');self.app.viewing_other=True
        self.app.handle_terminal(dict(type='error',code='cancelled',message='Cancelled',log='log'))
        self.assertEqual(self.app.result['result_state'],'complete')
        self.assertEqual(self.app.new_result['result_state'],'cancelled')
        self.app.open_new();self.assertEqual(self.app.result['result_state'],'cancelled')

if __name__=='__main__':unittest.main()

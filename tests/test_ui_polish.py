"""Presentation contracts that protect result meaning and native interaction."""
import copy
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from analyzer_theme import readable_timestamp
from analyzer_visuals import build_visual_evidence, html_visuals
from test_gui import FakeController, catalogue_fixture
from test_usability import sample
from test_v07 import payload


class TimestampTests(unittest.TestCase):
    def test_timestamp_requires_explicit_timezone_and_preserves_instant(self):
        stamp='2026-10-15T12:34:00+00:00'
        local=dt.datetime.fromisoformat(stamp).astimezone()
        text=readable_timestamp(stamp)
        self.assertIn(local.strftime('%d %b %Y, %H:%M'),text)
        self.assertIn('UTC',text)
        self.assertIn('timezone not recorded',readable_timestamp('2026-10-15T12:34:00'))
        self.assertEqual(readable_timestamp(None),'Not recorded')
        self.assertIn('unrecognized',readable_timestamp('bad timestamp'))


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'Native Tk display required')
class PolishWindowTests(unittest.TestCase):
    def setUp(self):
        import analyzer_gui as gui
        self.gui=gui;self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        catalogue_fixture(self.root);self.window=gui.tk.Tk();self.window.withdraw()
        self.controller=FakeController();self.app=gui.AnalyzerApp(self.window,self.root,self.controller,autostart=False)
        self.app.ready=True

    def tearDown(self):
        self.app.destroy();self.temp.cleanup()

    def test_partial_states_clear_previous_probabilities_and_reliability(self):
        self.app.display_result(sample())
        self.assertEqual(self.app.matchup_panel.values['a'].get(),'60.0%')
        for state in ('comparison','pending','cancelled','failed'):
            value=sample(state)
            self.app.display_result(value)
            self.assertEqual(self.app.matchup_panel.values['a'].get(),'—')
            self.assertEqual(self.app.matchup_panel.reliability.get(),'')
            self.assertFalse(self.app.probability.winfo_manager())
            self.assertFalse(self.app.probability.find_all())
        self.app.matchup_panel.show(dict(sample('cancelled'),quick_comparison=True))
        self.assertIn('cancelled',self.app.matchup_panel.mode.get())

    def test_frozen_evidence_never_tracks_changed_inputs(self):
        value=payload();before=copy.deepcopy(value)
        self.app.display_result(value)
        self.app.names['a'].set('Unrelated fighter');self.app.date.set('2020-01-01')
        self.app.change_font();self.app.draw_probability()
        self.assertEqual(value,before)
        self.assertIn('0 eligible UFC bouts',self.app.evidence_panel.text())
        self.assertIn('Methodology audit failed',self.app.evidence_panel.text())
        self.assertIn('prior-only',self.app.evidence_panel.text())
        self.app.display_result(sample())
        self.assertIn('not recorded',self.app.evidence_panel.text())

    def test_idle_running_and_commit_controls_have_distinct_states(self):
        self.app.controls();self.assertFalse(self.app.cancel_button.winfo_manager());self.assertFalse(self.app.progress.winfo_manager())
        self.controller.busy=True;self.controller.cancellable=True;self.app.controls()
        self.assertEqual(str(self.app.cancel_button['state']),'normal');self.assertEqual(self.app.progress.winfo_manager(),'grid')
        self.assertEqual(self.app.command_state('update'),'disabled')
        self.controller.cancellable=False;self.app.controls()
        self.assertEqual(str(self.app.cancel_button['state']),'disabled');self.assertIn('unavailable',self.app.operation_hint.get())
        self.controller.busy=False;self.app.controls()
        self.assertFalse(self.app.progress.winfo_manager());self.assertFalse(self.app.cancel_button.winfo_manager())

    def test_semantic_navigation_and_all_maintenance_commands_are_available(self):
        app=self.app
        self.assertEqual([app.notebook.tab(tab,'text') for tab in app.notebook.tabs()],['Overview','Statistics','Charts','Recent fights','Report'])
        self.assertEqual(set(app.commands),{'instructions','validation','update','status','recheck','restore','doctor','diagnostics','rebuild','cache','import','undo'})
        for key in ('instructions','validation'):self.assertIs(app.commands[key][0],app.help_menu)
        for key in ('update','status','recheck','restore','doctor','diagnostics','rebuild','cache','import','undo'):self.assertIs(app.commands[key][0],app.data_menu)

    def test_long_names_and_extreme_probabilities_remain_separate_from_bar(self):
        value=sample();value.update(fighter_a='José '+('Longname '*9),fighter_b='Other '+('Fighter '*10),fighter_a_win_probability=.999,fighter_b_win_probability=.001)
        self.app.display_result(value);self.window.deiconify();self.window.geometry('960x760');self.window.update()
        self.assertEqual(self.app.matchup_panel.values['b'].get(),'0.1%')
        self.assertEqual(self.app.matchup_panel.names['a'].get(),value['fighter_a'])
        self.assertFalse(any(self.app.probability.type(item)=='text' for item in self.app.probability.find_all()))

    def test_missing_metric_is_not_drawn_as_zero_and_points_are_keyboard_readable(self):
        value=sample();value['visual_evidence']=build_visual_evidence(value,{'fighter_a':[
            dict(date='2020-01-01',opponent='Opponent',result='W',division='Lightweight',overall=1500,division_elo=1500)]})
        before=copy.deepcopy(value)
        self.app.display_result(value);panel=self.app.visual_panel;panel.draw()
        labels=[panel.canvas.itemcget(item,'text') for item in panel.canvas.find_all() if panel.canvas.type(item)=='text']
        self.assertIn('Unavailable',labels)
        self.assertTrue(any(label=='A: 0.00' for label in labels))
        panel.step_point(1);self.assertIn('Bout 1',panel.inspection.get());self.assertIn('1500',panel.inspection.get())
        self.assertEqual(value,before)
        self.assertGreater(int(panel.trend['highlightthickness']),0)
        self.assertGreater(int(panel.scroll.canvas['highlightthickness']),0)
        html=html_visuals(value);self.assertIn('Successive',html.title())
        self.assertIn('José Alpha',html);self.assertIn('<circle',html)


if __name__=='__main__':unittest.main()

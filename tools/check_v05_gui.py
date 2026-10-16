"""Owned native window checks for frozen summaries, correction review and comparison."""
import argparse
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import analyzer_gui as gui
from analyzer_support import atomic_json
from analyzer_comparison import compare_entries,format_comparison
from test_gui import FakeController
from tools.capture_window import capture

def buttons(parent):
    found=[]
    for child in parent.winfo_children():
        if isinstance(child,gui.ttk.Button):found.append(child)
        found.extend(buttons(child))
    return found

def main():
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--preview',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    payload=json.loads(args.fixture.read_text(encoding='utf-8'));preview=json.loads(args.preview.read_text(encoding='utf-8'))
    gui.enable_dpi_awareness();window=gui.tk.Tk();controller=FakeController();app=gui.AnalyzerApp(window,controller=controller,autostart=False)
    app.ready=True;app.display_result(payload);app.toggle_inputs() if not app.collapsed else None
    checks=[]
    try:
        for size in ('Medium','Large'):
            app.font_size.set(size);app.change_font();window.update();app.notebook.select(app.overview);window.update()
            assert app.overview_tree.winfo_height()>50,app.overview_tree.winfo_height()
            assert app.evidence_panel.winfo_height()>50
            assert payload['matchup_summary']['observations'][0]['text'] in app.matchup_observations.get()
            app.summary_metrics();window.update();assert app.notebook.select()==str(app.comparison)
            checks.append('Overview summary and supporting metric navigation: '+size)
        app.font_size.set('Medium');app.change_font();app.notebook.select(app.overview);window.update()
        capture(window,args.out.parent/'overview.png')
        a=dict(payload=payload,request={'sex':'men','operation':'predict'},context={'datasets':{'raw':'before'}})
        b=copy.deepcopy(a);b['payload']['fighter_a_win_probability']+=.01;b['payload']['fighter_b_win_probability']-=.01;b['context']['datasets']['raw']='after'
        value=compare_entries(a,b);app.comparison_dialog(value);window.update()
        dialog=next(d for d in window.winfo_children() if isinstance(d,gui.tk.Toplevel) and d.title()=='Compare saved versions')
        assert any(w.cget('text')=='Save HTML' for w in buttons(dialog))
        controller.busy=True
        next(w for w in buttons(dialog) if w.cget('text')=='Open original').invoke();assert app.viewing_other
        controller.busy=False;dialog.destroy();checks.append('Comparison preserves opened report during background work')
        app.corrections_dialog(preview);window.update()
        dialog=next(d for d in window.winfo_children() if isinstance(d,gui.tk.Toplevel))
        next(w for w in buttons(dialog) if w.cget('text')=='Apply captured corrections').invoke()
        assert controller.request['operation']=='apply_corrections' and controller.request['preview_id']==preview['id']
        controller.busy=False;checks.append('Apply sends the reviewed preview identity, without another fetch')
        app.controls();controller.busy=True;app.controls()
        for key in ('recheck','cache'):assert app.command_state(key)=='disabled'
        controller.busy=False;checks.append('Recheck and cache clearing disabled during an active job')
        atomic_json(args.out,dict(status='PASS',checks=checks,actual_window_size=[window.winfo_width(),window.winfo_height()]))
    finally:controller.busy=False;app.destroy()

if __name__=='__main__':main()

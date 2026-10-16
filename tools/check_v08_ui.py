"""Owned native windows, frozen fixtures and explicit v0.8 interaction checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import analyzer_gui as gui
from analyzer_bout_context import FightSource,capture,validate_context
from analyzer_fight_history import recent_fights
from analyzer_support import atomic_json
from tools.capture_window import capture as screenshot

class Idle:
    busy=False;cancellable=False;started=0
    def poll(self):return []
    def start(self,request):self.request=request;self.busy=True;self.started=time.monotonic()
    def terminate(self):self.busy=False

def children(widget):
    for child in widget.winfo_children():
        yield child;yield from children(child)

def main():
    out=ROOT/'work/v0.8/ui';out.mkdir(parents=True,exist_ok=True)
    records=[];fixtures={}
    for sex in ('men','women'):
        fresh=ROOT/f'work/v0.8/final-benchmarks/predict-{sex}-candidate-1.json'
        if fresh.exists():
            p=json.loads(fresh.read_text(encoding='utf-8'))
            p['ui_review_fixture']='Copy of a fresh v0.8 prediction; rendering must not alter captured evidence.'
        else:
            p=json.loads((ROOT/f'work/ui-polish/fixtures/{sex}.json').read_text(encoding='utf-8'))
            identities={side:(p[side],p[side+'_id']) for side in ('fighter_a','fighter_b')}
            source=FightSource(ROOT,sex,identities)
            history=recent_fights(ROOT,sex,identities['fighter_a'],identities['fighter_b'],p['fight_date'],limit=None,source=source)
            p.update(capture(source,history))
            p['ui_review_fixture']='v0.7 frozen prediction plus current source evidence for native rendering checks; not a new forecast'
        p.pop('history_id',None)
        validate_context(p);fixtures[sex]=p;atomic_json(out/(sex+'-fixture.json'),p)
    gui.enable_dpi_awareness()
    with tempfile.TemporaryDirectory() as folder:
        window=gui.tk.Tk();controller=Idle();app=gui.AnalyzerApp(window,Path(folder),controller,False)
        try:
            window.geometry('1150x850+10+10')
            for sex,p in fixtures.items():
                frozen=copy.deepcopy(p)
                division=p.get('division','Lightweight').replace("Women's ",'')
                app.division.set(('Women' if sex=='women' else 'Men')+' — '+division);app.change_division()
                app.date.set(p['fight_date'])
                for side in ('a','b'):app.names[side].set(p['fighter_'+side])
                app.display_result(p);app.ready=True;app.controls()
                app.freshness.set('Displayed snapshot through '+str(p.get('evidence_quality',{}).get('data_through','unavailable')))
                if not app.collapsed:app.toggle_inputs()
                for size in ('Small','Medium','Large'):
                    app.font_size.set(size);app.change_font();window.update()
                    app.notebook.select(app.recent_tab);window.update()
                    tree=app.recent_trees['fighter_a'];tree.selection_set('0');app.recent_selection('fighter_a')
                    panel=app.bout_panels['fighter_a']
                    start=time.monotonic()
                    if not panel.expanded:panel.toggle()
                    window.update();elapsed=time.monotonic()-start
                    assert panel.value and panel.text.get('1.0','end').strip()
                    if size=='Medium':screenshot(window,out/(sex+'-bout-details.png'))
                    panel.toggle();app.open_recent_form();window.update()
                    form=app.recent_form_panel
                    start=time.monotonic();form.window.set('3');form.render();window.update()
                    form_seconds=time.monotonic()-start
                    assert len(form.tree.get_children())==14
                    form.window.set('5');form.render();window.update()
                    if size=='Medium':screenshot(window,out/(sex+'-recent-form.png'))
                    records.append(dict(sex=sex,text=size,bout_expand_seconds=elapsed,form_switch_seconds=form_seconds))
                assert p==frozen,'Rendering mutated a frozen report'
            # Drive the real refresh dialog using a fake computation controller.
            original=copy.deepcopy(fixtures['men']);app.display_result(original);app.ready=True
            app.catalogs={'men':SimpleNamespace(resolve=lambda n,i:(n,i))}
            app.refresh_dialog()
            dialogs=[w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel)]
            dialog=dialogs[-1];window.update();screenshot(dialog,out/'refresh-options.png')
            next(w for w in children(dialog) if isinstance(w,gui.ttk.Button) and w.cget('text')=='Refresh and compare').invoke()
            assert controller.request['skip_saved_result'] and controller.request['use_cache']
            assert controller.request['fight_date']==original['fight_date']
            controller.busy=False
            fresh=copy.deepcopy(original);fresh['generated_at']='2026-10-16T12:00:00+00:00'
            app.handle_terminal(dict(type='result',operation='predict',payload=fresh));window.update()
            dialog=[w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel)][-1]
            screenshot(dialog,out/'refresh-comparison.png');dialog.destroy()
            assert original==fixtures['men'],'Refresh overwrote the original report'
            # Error/cancel retains displayed source rather than replacing it with preview.
            app.display_result(original);app.active_refresh={'original':{},'displayed':app.result}
            app.preview=dict(fresh,result_state='pending')
            app.handle_terminal(dict(type='error',code='cancelled',message='Cancelled'))
            assert app.result is original and app.active_refresh is None
            assert app.new_result['result_state']=='cancelled' and app.open_new_button.cget('text')=='Open partial report'
            for percent in (100,125,150,200):
                window.tk.call('tk','scaling',(96/72)*percent/100)
                app.font_size.set('Large');app.change_font();window.update()
                for tab in app.tabs.values():app.notebook.select(tab);window.update()
            atomic_json(out/'verification.json',dict(status='PASS',interactions=records,
                frozen_reports_unchanged=True,refresh_success_cancel=True,
                scaling='Simulated Tk 100/125/150/200%; no clean OS or physical alternate DPI claims'))
        finally:controller.busy=False;app.destroy()
    print('v0.8 native interactions PASS',flush=True)
if __name__=='__main__':main()

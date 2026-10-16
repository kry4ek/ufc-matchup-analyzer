"""Real native worker stages, numerical parity, frozen visuals and upgrade import."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time

def main():
    p=argparse.ArgumentParser();p.add_argument('--app-root',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--baseline-dir',type=Path,required=True);p.add_argument('--resume',action='store_true');p.add_argument('--fight-date',default='2026-10-10');p.add_argument('--as-of-date');args=p.parse_args()
    if args.app_root:sys.path.insert(0,str(args.app_root.resolve()))
    import analyzer_gui as gui
    from analyzer_support import ROOT,atomic_json,digest
    from analyzer_history import History
    from analyzer_results import format_result
    from analyzer_reporting import format_html
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from tools.capture_window import capture
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]='http://127.0.0.1:9'
    os.environ['NO_PROXY']=''
    gui.messagebox.showerror=lambda *a,**kw:None;gui.messagebox.showinfo=lambda *a,**kw:None;gui.messagebox.askyesno=lambda *a,**kw:True
    gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',runs=[],checks=[])
    if args.resume:report=json.loads(args.out.read_text(encoding='utf-8'))
    completed={row['sex'] for row in report['runs']}
    def wait():
        started=time.monotonic()
        while time.monotonic()-started<1200:
            window.update()
            if not app.controller.busy:
                if not app.ready:raise AssertionError(app.status.get())
                return time.monotonic()-started
            time.sleep(.04)
        raise TimeoutError(app.status.get())
    try:
        window.update();wait()
        for sex,names,division in [('men',('Islam Makhachev','Justin Gaethje'),'Lightweight'),('women',('Valentina Shevchenko','Manon Fiorot'),'Flyweight')]:
            if sex in completed:continue
            app.division.set(('Men' if sex=='men' else 'Women')+' — '+division);app.change_division();app.names['a'].set(names[0]);app.names['b'].set(names[1]);app.date.set(args.fight_date);window.update()
            request=app.prediction_request(1);request.update(force_recalculate=True,use_cache=False)
            if sex=='men' and args.as_of_date:request['as_of_date']=args.as_of_date
            app.start(request);seconds=wait();value=copy.deepcopy(app.result)
            assert value['result_state']=='complete',app.status.get()
            baseline=json.loads((args.baseline_dir/('baseline-'+sex+'.json')).read_text(encoding='utf-8'))
            assert abs(value['fighter_a_win_probability']-baseline['fighter_a_win_probability'])<=1e-12
            for side in ('a','b'):
                for name,number in baseline['fighter_'+side+'_comparison'].items():
                    current=value['fighter_'+side+'_comparison'].get(name)
                    if isinstance(number,(int,float)):assert abs(current-number)<=1e-12,(side,name)
                    else:assert current==number,(side,name)
            events=[json.loads(line) for line in app.controller.events_path.read_text(encoding='utf-8').splitlines()]
            types=[event['type'] for event in events]
            assert types.index('initial_ready')<types.index('comparison_ready')<types.index('result'),types
            initial=next(e['payload'] for e in events if e['type']=='initial_ready')
            assert not any(k in initial for k in ('fighter_a_win_probability','predicted_winner','reliability_label'))
            assert initial['recent_fights']==value['recent_fights']
            assert initial['fighter_a_id']==value['fighter_a_id']
            record=value['visual_evidence'];assert record['bars'] and all(record['elo'].get(side) for side in ('fighter_a','fighter_b'))
            for points in record['elo'].values():assert all(point['date']<value['fight_date'] for point in points)
            app.notebook.select(app.visual_tab);window.update()
            for size in ('Small','Medium','Large'):
                app.font_size.set(size);app.change_font();window.update();assert app.visual_panel.table.winfo_height()>25
            app.font_size.set('Medium');app.change_font()
            if not app.collapsed:app.toggle_inputs()
            window.update();capture(window,args.out.parent/(sex+'-visual.png'))
            text=format_result(value);html=format_html(value)
            assert 'VISUAL EVIDENCE' in text and '<svg' in html
            for extension,content in (('txt',text),('html',html)): (args.out.parent/(sex+'-report.'+extension)).write_text(content,encoding='utf-8')
            app.copy();window.update();assert window.clipboard_get()==text
            atomic_json(args.out.parent/(sex+'-result.json'),value)
            # Real older payload remains frozen through import/open/export, with no cache copy.
            old=args.out.parent/('old-'+sex);old.mkdir(exist_ok=True);(old/'analyzer_support.py').write_text('')
            old_history=History(old);legacy=copy.deepcopy(baseline);legacy.pop('visual_evidence',None);legacy.pop('history_id',None)
            original_request=legacy.get('calculation_request',value['calculation_request']);original_context={}
            old_id=old_history.save(original_request,original_context,legacy)
            before=digest(old_history.directory/(old_id+'.json'))
            atomic_json(old/'.runtime/ui_preferences.json',dict(text_size='Large',inputs_collapsed=True,geometry='900x700',division=app.division.get(),fighter_a=names[0],fighter_b=names[1]))
            original_preferences=digest(old/'.runtime/ui_preferences.json');previous_size=app.font_size.get()
            gui.filedialog.askdirectory=lambda **kw:str(old)
            app.import_dialog();window.update()
            review=next(w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel) and w.title()=='Review previous analyses')
            toggle=next(w for w in review.winfo_children() if isinstance(w,gui.ttk.Checkbutton));toggle.invoke()
            button=next(w for w in review.winfo_children() if isinstance(w,gui.ttk.Button) and w.cget('text')=='Import reviewed analyses');button.invoke();wait()
            assert app.font_size.get()=='Large' and app.collapsed
            saved=next(e for e in History(ROOT).entries() if e['id']==old_id)
            assert saved['payload']==legacy and digest(old_history.directory/(old_id+'.json'))==before
            assert digest(old/'.runtime/ui_preferences.json')==original_preferences
            assert not saved['payload'].get('visual_evidence')
            app.display_result(saved['payload']);window.update();assert 'Elo trend was not saved' in format_result(saved['payload'])
            app.undo_import();wait();assert not (History(ROOT).directory/(old_id+'.json')).exists()
            assert app.font_size.get()==previous_size
            report['runs'].append(dict(sex=sex,seconds=round(seconds,3),initial_seconds=value['time_to_initial_seconds'],probability=value['fighter_a_win_probability'],
                                       initial_advanced_final_order='PASS',baseline_probability_and_metrics='PASS',visual_export_and_import='PASS'))
            atomic_json(args.out,report)
        app.validation_dialog();window.update()
        dialog=next(w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel) and w.title()=='Model validation')
        def descendants(parent):
            for widget in parent.winfo_children():
                yield widget
                yield from descendants(widget)
        texts=[w.get('1.0','end') for w in descendants(dialog) if isinstance(w,gui.tk.Text)]
        assert texts and 'LIMITED_RETROSPECTIVE_EVALUATION' in texts[0],texts
        dialog.destroy();report['checks'].append('Dated validation report shown offline')
        report['status']='PASS';atomic_json(args.out,report)
    finally:
        if app.controller.busy:app.controller.terminate()
        app.destroy()
if __name__=='__main__':main()

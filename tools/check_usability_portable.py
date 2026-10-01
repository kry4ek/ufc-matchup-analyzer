"""Verify v0.3 states and reuse through the extracted application's real workers."""
import argparse
import json
import os
from pathlib import Path
import time
import analyzer_gui as gui
from analyzer_reporting import report_sections, format_html
from analyzer_support import ROOT, atomic_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]='http://127.0.0.1:9'
    os.environ['NO_PROXY']=''
    errors=[]
    gui.messagebox.showerror=lambda *a,**k:errors.append(str(a))
    gui.messagebox.showinfo=lambda *a,**k:None
    gui.messagebox.askyesno=lambda *a,**k:True
    gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window)
    report=dict(status='RUNNING',checks=[])
    def record(name,**details):
        report['checks'].append(dict(name=name,status='PASS',**details));atomic_json(args.out,report)
    def wait(limit=1200):
        started=time.monotonic()
        while time.monotonic()-started<limit:
            window.update()
            if not app.controller.busy and app.ready:return round(time.monotonic()-started,3)
            if errors:raise AssertionError(errors)
            time.sleep(.04)
        raise TimeoutError(app.status.get())
    def select(sex,a,b,date='2026-10-10'):
        app.division.set(('Men — Lightweight' if sex=='men' else 'Women — Flyweight'));app.change_division()
        app.names['a'].set(a);app.names['b'].set(b);app.date.set(date);window.update()
    def events():return [json.loads(line) for line in app.controller.events_path.read_text(encoding='utf-8').splitlines()]
    try:
        window.update();wait(90)
        for sex,a,b in [('men','Islam Makhachev','Justin Gaethje'),('women','Valentina Shevchenko','Manon Fiorot')]:
            select(sex,a,b);app.compare();seconds=wait();value=dict(app.result)
            assert value['result_state']=='comparison' and not value.get('reused')
            assert not any(field in value for field in ('fighter_a_win_probability','predicted_winner','reliability_label','confidence_tier'))
            stages=[e.get('stage') for e in events() if e['type']=='progress']
            assert not any(s in ('training','cross_validation','prediction') for s in stages),stages
            assert sum(len(s['rows']) for s in report_sections(value))>70
            assert all(value['fighter_'+side+'_comparison']['history_max_event_date_before']<value['fight_date'] for side in ('a','b'))
            record(sex+' statistics-only without prediction fitting',seconds=seconds,first_comparison_seconds=value['time_to_comparison_seconds'],stages=stages)
            count=len(app.history.entries());previous_job=app.controller.job_id;displayed=app.result
            app.compare();seconds=wait()
            assert app.result is displayed and app.controller.job_id==previous_job
            assert len(app.history.entries())==count and app.notebook.select()==str(app.comparison)
            assert app.result['generated_at']==value['generated_at'];assert report_sections(app.result)==report_sections(value)
            record(sex+' existing statistics navigation without another worker',seconds=seconds,history_entries=count)
            app.filter.set('Elo');window.update();complete=app.result_text;app.copy();window.update();assert window.clipboard_get()==complete
            output=args.out.parent/(sex+' comparison.html');gui.filedialog.asksaveasfilename=lambda **kw:str(output)
            app.save();assert output.read_text(encoding='utf-8')==format_html(app.result)
            assert 'STRIKING' in output.read_text(encoding='utf-8')
            record(sex+' filtered-view complete TXT/HTML/clipboard values')
        # Zero-history warning is explicit, and a declined confirmation starts no job.
        select('women','Valentina Shevchenko','Manon Fiorot','1985-01-01')
        confirmed=[];gui.messagebox.askyesno=lambda *a,**k:confirmed.append(str(a)) or False
        app.compare();assert confirmed and not app.controller.busy
        app.refresh_coverage();assert 'no eligible' in app.coverage_warning.get().lower()
        record('zero dated history requires explicit confirmation')
        gui.messagebox.askyesno=lambda *a,**k:True
        # Cancellation after real preparation retains its metrics and creates no history entry.
        select('women','Valentina Shevchenko','Manon Fiorot','2026-10-11')
        count=len(app.history.entries());app.analyze();started=time.monotonic()
        while app.preview is None and time.monotonic()-started<90:
            window.update();time.sleep(.04)
        assert app.preview is not None and app.result['result_state']=='pending'
        preview=report_sections(app.result);assert app.controller.cancellable;app.cancel();wait(90)
        assert app.result['result_state']=='cancelled' and report_sections(app.result)==preview
        assert len(app.history.entries())==count and not app.controller.busy
        record('real comparison preview before training, then cancellation',seconds=round(time.monotonic()-started,3))
        # Disable history without deleting existing completed entries.
        app.history_setting.set(False);app.save_history_setting();count=len(app.history.entries())
        select('women','Valentina Shevchenko','Manon Fiorot');app.compare();wait()
        assert not app.result.get('reused') and len(app.history.entries())==count
        record('history disabled stops both reuse and storage')
        app.history_setting.set(True);app.save_history_setting()
        report.update(status='PASS',offline=True);atomic_json(args.out,report)
    finally:
        if app.controller.busy:app.controller.terminate()
        app.destroy()

if __name__=='__main__':main()

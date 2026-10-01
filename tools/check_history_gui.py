"""Exercise real history dialogs during a job and preserve reports on failure."""
import argparse,json,os,time
from pathlib import Path
import analyzer_gui as gui
from analyzer_support import atomic_json
from analyzer_reporting import report_sections

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--fixture',type=Path,required=True);args=parser.parse_args()
    for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]='http://127.0.0.1:9'
    os.environ['NO_PROXY']=''
    errors=[];gui.messagebox.showerror=lambda *a,**k:errors.append(str(a));gui.messagebox.showinfo=lambda *a,**k:None;gui.messagebox.askyesno=lambda *a,**k:True
    gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window);report=dict(status='RUNNING',checks=[])
    def wait(limit=1200):
        deadline=time.monotonic()+limit
        while time.monotonic()<deadline:
            window.update()
            if not app.controller.busy and app.ready:return
            time.sleep(.04)
        raise TimeoutError(app.status.get())
    def record(name):report['checks'].append(dict(name=name,status='PASS'));atomic_json(args.out,report)
    def recent():
        app.show_history();window.update()
        dialog=next(w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel) and w.title()=='Recent analyses')
        frame=next(w for w in dialog.winfo_children() if isinstance(w,gui.ttk.Frame))
        tree=next(w for w in frame.winfo_children() if isinstance(w,gui.ttk.Treeview))
        buttons=next(w for w in frame.winfo_children() if isinstance(w,gui.ttk.Frame))
        return dialog,tree,{w.cget('text'):w for w in buttons.winfo_children()}
    try:
        window.update();wait(90)
        app.history.clear()  # This tool must run on a disposable test bundle.
        app.division.set('Women — Flyweight');app.change_division();app.names['a'].set('Valentina Shevchenko');app.names['b'].set('Manon Fiorot');app.date.set('2026-10-10');app.compare();wait()
        assert app.result['result_state']=='comparison' and len(app.history.entries())==1
        app.date.set('2026-10-11');app.analyze();deadline=time.monotonic()+90
        while app.preview is None and time.monotonic()<deadline:window.update();time.sleep(.04)
        assert app.preview is not None and app.controller.busy
        prepared=report_sections(app.preview)
        dialog,tree,buttons=recent();tree.selection_set(tree.get_children()[0]);buttons['Open'].invoke();window.update()
        assert app.controller.busy and app.viewing_other and app.result['fight_date']=='2026-10-10'
        app.copy();window.update();assert window.clipboard_get()==app.result_text
        app.cancel();wait(90)
        assert app.result['fight_date']=='2026-10-10' and app.new_result['result_state']=='cancelled'
        assert len(app.history.entries())==1
        app.open_new();assert app.result['result_state']=='cancelled' and report_sections(app.result)==prepared
        record('Open history while training; retain, open and copy cancelled comparison')
        fixture=json.loads(args.fixture.read_text());app.preview=dict(fixture,result_state='pending')
        app.handle_terminal(dict(type='result',operation='predict',payload=fixture));assert app.preview is None
        expected=app.result_text;app.start(dict(operation='update',max_events=1));wait(120)
        assert errors and app.result_text==expected and app.result['result_state']=='complete'
        app.copy();window.update();assert window.clipboard_get()==expected
        record('Real network maintenance failure preserves a displayed completed prediction fixture')
        dialog,tree,buttons=recent();tree.selection_set(tree.get_children()[0]);buttons['Delete selected'].invoke();assert not app.history.entries();dialog.destroy()
        record('Native recent-history dialog deletes selected analysis')
        app.date.set('2026-10-12');app.compare();wait();assert app.history.entries()
        dialog,tree,buttons=recent();buttons['Clear history'].invoke();assert not app.history.entries();dialog.destroy()
        record('Explicit Clear history removes entries and preserves displayed report')
        assert app.result_text
        report['status']='PASS';atomic_json(args.out,report)
    finally:
        if app.controller.busy:app.controller.terminate()
        app.destroy()

if __name__=='__main__':main()

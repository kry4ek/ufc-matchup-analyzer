"""Native live update, honest progress, recovery and manual-retry verification."""
import argparse
import json
import os
from pathlib import Path
import time
import analyzer_gui as gui
from analyzer_support import ROOT,atomic_json,digest,manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    if not (ROOT.parent/'DISPOSABLE_V04_CHECK').is_file():raise ValueError('Use a marked disposable portable extraction')
    gui.messagebox.showinfo=lambda *a,**k:None;gui.messagebox.askyesno=lambda *a,**k:True
    unexpected=[];gui.messagebox.showerror=lambda *a,**k:unexpected.append(str(a))
    gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window)
    terminals=[];original=app.handle_terminal
    def terminal(event):terminals.append(event);original(event)
    app.handle_terminal=terminal
    def wait(previous,limit=1800):
        started=time.monotonic();ticks=0
        while time.monotonic()-started<limit:
            window.update();ticks+=1
            if not app.controller.busy and len(terminals)>previous:return terminals[-1],dict(seconds=round(time.monotonic()-started,3),gui_ticks=ticks)
            time.sleep(.04)
        raise TimeoutError(app.status.get())
    def operation(request):
        previous=len(terminals);app.start(request);event,timing=wait(previous)
        print(request['operation']+': '+event['type']+' '+str(event.get('payload',{}).get('status',event.get('code',''))),flush=True)
        return event,timing
    def hashes():return {r['path']:digest(ROOT/r['path']) for r in manifest()['files']}
    report=dict(status='RUNNING',checks=[])
    def record(name,event,timing):
        report['checks'].append(dict(name=name,type=event['type'],code=event.get('code'),transaction_status=event.get('payload',{}).get('status'),**timing));atomic_json(args.out,report)
    def close_dialogs():
        for dialog in window.winfo_children():
            if isinstance(dialog,gui.tk.Toplevel):dialog.destroy()
    saved_proxies={key:os.environ.get(key) for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY')}
    try:
        startup,timing=wait(0,300);assert startup['type']=='result' and app.ready,startup
        baseline=hashes()
        updated,timing=operation(dict(operation='update',max_events=2));record('real bounded all-target update',updated,timing)
        assert updated['type']=='result' and updated['payload']['ready'],updated
        summary=updated['payload']['summary'];report['summary']=summary
        records=[]
        for line in app.controller.events_path.read_text(encoding='utf-8').splitlines():
            event=json.loads(line)
            if event['type']=='progress':records.append(event)
        measured=[e for e in records if e.get('total')]
        assert measured and all(0<=e['completed']<=e['total'] for e in measured)
        assert all(not e['cancellable'] for e in records if e.get('stage')=='committing')
        report['measured_progress_events']=len(measured)
        if updated['payload']['status']=='committed':
            assert sum(v['captured_fights'] for v in summary.values())>0
            app.updated_fights_dialog();window.update()
            trees=[widget for dialog in window.winfo_children() if isinstance(dialog,gui.tk.Toplevel) for widget in dialog.winfo_children() if isinstance(widget,gui.ttk.Treeview)]
            assert trees and len(trees[0].get_children())==sum(v['captured_fights'] for v in summary.values())
            report['updated_fights_dialog_rows']=len(trees[0].get_children());close_dialogs()
        changed=hashes()
        repeated,timing=operation(dict(operation='update',max_events=2));record('real repeated update adds nothing',repeated,timing)
        assert repeated['type']=='result' and repeated['payload']['status']=='no_changes'
        assert hashes()==changed
        if updated['payload']['status']=='committed':
            restored,timing=operation(dict(operation='recover'));record('native restore previous datasets',restored,timing)
            assert restored['type']=='result' and restored['payload']['ready']
            assert restored['payload']['maintenance_status']['transaction_status']=='rolled_back'
        assert hashes()==baseline
        # Fail the actual HTTP request, then restore networking and invoke the
        # real dialog's Retry action on a fresh no-change check.
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]='http://127.0.0.1:9'
        os.environ['NO_PROXY']=''
        failed,timing=operation(dict(operation='update',max_events=1,from_date='2026-10-11'));record('native source fetch failure',failed,timing)
        assert failed['type']=='error' and failed['code']=='source_fetch_failed',failed
        error=failed['maintenance_error'];assert error['retryable'] and error['installation_state']=='unchanged'
        assert Path(error['diagnostics_path']).is_file() and hashes()==baseline
        dialog=next(w for w in window.winfo_children() if isinstance(w,gui.tk.Toplevel))
        buttons={w.cget('text'):w for frame in dialog.winfo_children() for w in frame.winfo_children() if isinstance(w,gui.ttk.Button)}
        assert 'Retry' in buttons and 'Copy diagnostics' in buttons
        buttons['Copy diagnostics'].invoke();assert 'source_fetch_failed' in window.clipboard_get()
        old_job=app.controller.job_id
        for key,value in saved_proxies.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        previous=len(terminals);buttons['Retry'].invoke();retry,timing=wait(previous)
        record('real dialog Retry with a fresh worker',retry,timing)
        assert app.controller.job_id!=old_job and retry['type']=='result' and retry['payload']['status']=='no_changes',retry
        assert hashes()==baseline and not unexpected,unexpected
        report.update(status='PASS',all_original_hashes_restored=True,diagnostics_path_retained=True)
        atomic_json(args.out,report)
    finally:
        for key,value in saved_proxies.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        if app.controller.busy:app.controller.terminate()
        app.destroy()

if __name__=='__main__':main()

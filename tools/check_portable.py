"""Exercise the real Tk → worker → engine route using the bundled interpreter."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys
import time

# In the embeddable runtime, explicit _pth entries select the packaged app.
import analyzer_gui as gui
from analyzer_support import ROOT,atomic_json
from analyzer_results import result_filename
from ufc_matchup_analyzer import process_peak_mib

def visible_owned_consoles():
    if os.name!='nt':return []
    import ctypes
    from ctypes import wintypes as wt
    class Entry(ctypes.Structure):
        _fields_=[('size',wt.DWORD),('usage',wt.DWORD),('pid',wt.DWORD),('heap',ctypes.c_size_t),('module',wt.DWORD),('threads',wt.DWORD),('parent',wt.DWORD),('priority',ctypes.c_long),('flags',wt.DWORD),('name',wt.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32');kernel.CreateToolhelp32Snapshot.restype=wt.HANDLE
    kernel.Process32FirstW.argtypes=[wt.HANDLE,ctypes.POINTER(Entry)];kernel.Process32NextW.argtypes=[wt.HANDLE,ctypes.POINTER(Entry)];kernel.CloseHandle.argtypes=[wt.HANDLE]
    snapshot=kernel.CreateToolhelp32Snapshot(2,0);parents={};owned={os.getpid()}
    try:
        entry=Entry();entry.size=ctypes.sizeof(entry);ok=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while ok:
            parents[entry.pid]=entry.parent;ok=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:kernel.CloseHandle(snapshot)
    while True:
        children={child for child,parent in parents.items() if parent in owned}
        if children<=owned:break
        owned.update(children)
    user=ctypes.WinDLL('user32');callback=ctypes.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
    user.GetWindowThreadProcessId.argtypes=[wt.HWND,ctypes.POINTER(wt.DWORD)];user.GetClassNameW.argtypes=[wt.HWND,wt.LPWSTR,ctypes.c_int];user.IsWindowVisible.argtypes=[wt.HWND];user.EnumWindows.argtypes=[callback,wt.LPARAM]
    visible=[]
    @callback
    def inspect(hwnd,_):
        pid=wt.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value in owned and user.IsWindowVisible(hwnd):
            name=ctypes.create_unicode_buffer(256);user.GetClassNameW(hwnd,name,256)
            if name.value in ('ConsoleWindowClass','CASCADIA_HOSTING_WINDOW_CLASS'):visible.append(name.value)
        return True
    user.EnumWindows(inspect,0);return visible

def main():
    p=argparse.ArgumentParser();p.add_argument('--target',choices=['men','women','quick'],default='quick');p.add_argument('--out',type=Path,required=True);p.add_argument('--screenshots',type=Path);p.add_argument('--full',action='store_true');p.add_argument('--baseline',type=Path);p.add_argument('--offline',action='store_true')
    p.add_argument('--fighter-a');p.add_argument('--fighter-b');p.add_argument('--division');p.add_argument('--fight-date',default='2026-10-10');p.add_argument('--startup-timeout',type=float,default=300,help='Seconds allowed for first-use integrity and native-library checks');args=p.parse_args()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    package=ROOT.parent.resolve()
    assert Path(sys.executable).resolve().is_relative_to(package)
    assert all(Path(path).resolve().is_relative_to(package) for path in sys.path),sys.path
    dialogs=[]
    gui.messagebox.showerror=lambda *a,**k:dialogs.append(('error',str(a)))
    gui.messagebox.showinfo=lambda *a,**k:dialogs.append(('info',str(a)))
    gui.messagebox.askyesno=lambda *a,**k:False
    if args.offline:
        # Block actual engine subprocess requests through dead local proxies. The
        # integrity guard ensures this is not a cached prediction.
        for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):os.environ[name]='http://127.0.0.1:9'
        os.environ['NO_PROXY']=''
    gui.enable_dpi_awareness();window=gui.tk.Tk();app=gui.AnalyzerApp(window)
    report=dict(python=sys.version.split()[0],interpreter=str(sys.executable),tk=window.tk.call('package','provide','Tk'),runs=[],offline=args.offline)
    def wait(limit=1200):
        started=time.monotonic();ticks=0;peak=0;next_sample=0
        while time.monotonic()-started<limit:
            window.update();ticks+=1
            if time.monotonic()-started>=next_sample:
                peak=max(peak,process_peak_mib(os.getpid()) or 0);next_sample+=1
                assert not visible_owned_consoles(),'A visible console belongs to this app process tree'
            if not app.controller.busy and app.ready:return dict(seconds=round(time.monotonic()-started,2),gui_ticks=ticks,full_app_process_tree_working_set_mib=round(peak,1),visible_owned_console_windows=0)
            if not app.controller.busy and any(kind=='error' for kind,_ in dialogs):raise AssertionError(dialogs)
            time.sleep(.05)
        raise TimeoutError(app.status.get())
    try:
        window.update();time.sleep(.1);window.update();report['startup']=wait(args.startup_timeout)
        report['freshness']=app.freshness.get()
        if args.target=='quick':
            report['status']='PASS';atomic_json(args.out,report);return
        sex=args.target;division='Lightweight' if sex=='men' else 'Flyweight'
        a,b=('Islam Makhachev','Justin Gaethje') if sex=='men' else ('Valentina Shevchenko','Manon Fiorot')
        a=args.fighter_a or a;b=args.fighter_b or b;division=args.division or division
        cases=[('forward',a,b,args.fight_date,None)]
        if args.full:cases += [('reverse',b,a,'2026-10-10',None),('single-worker',a,b,'2026-10-10',1),('historical',a,b,'2025-01-18' if sex=='men' else '2025-05-10',1)]
        forward=None
        for label,fighter_a,fighter_b,date,workers in cases:
            dialogs.clear();app.division.set(('Men' if sex=='men' else 'Women')+' — '+division);app.change_division()
            app.names['a'].set(fighter_a);app.names['b'].set(fighter_b);app.date.set(date)
            previous=app.result
            request=app.prediction_request(workers);request.update(use_cache=False,force_recalculate=True)
            app.start(request)
            app.analyze()  # A repeated click must not create another worker.
            timing=wait()
            assert app.result is not previous,(label,dialogs)
            payload=dict(app.result)
            assert not payload.get('reused'), 'Regression checks must compute fresh results'
            if args.baseline:
                baseline_path=args.baseline if label=='forward' else args.baseline.parent/(sex+'-'+label+'.json')
                baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
                assert abs(payload['fighter_a_win_probability']-baseline['fighter_a_win_probability'])<1e-12
                for side in ('a','b'):
                    original=baseline['fighter_'+side+'_comparison'];current=payload['fighter_'+side+'_comparison']
                    assert all(current.get(name)==value for name,value in original.items()),(label,side,'comparison changed')
            assert payload['model_version']==('v3_bayes_smoothed' if sex=='men' else 'v1_current_ensemble')
            assert 0<=payload['fighter_a_win_probability']<=1 and abs(payload['fighter_a_win_probability']+payload['fighter_b_win_probability']-1)<1e-8
            assert all(section in app.result_text for section in ('Overall Elo','Division Elo','Avg opponent Elo','STRIKING','GRAPPLING','RECENT FORM AND ACTIVITY','BAYESIAN MODEL RATE ESTIMATES','MODEL DETAILS','RELIABILITY AND DATA QUALITY'))
            if sex=='women':
                assert abs(sum(payload['model_weights'].values())-1)<1e-12
                weighted=sum(row['fighter_a_win_probability']*payload['model_weights'][row['model']] for row in payload['model_predictions'] if row['model']!='ensemble_average')
                assert abs(weighted-payload['fighter_a_win_probability'])<1e-12
                assert len(payload['reliability_factors'])>0
            else:
                assert all(field in payload['fighter_a_comparison'] for field in ('avg_prior_opponent_elo_refined','recent_avg_opponent_elo','best_prior_opponent_elo','finish_wins_before','decision_experience'))
                assert all(label in app.result_text for label in ('All-history opponent Elo (refined)','Strongest opponent faced (Elo)','Finish wins','Decision experience (fights)'))
            assert all(payload['fighter_'+side+'_comparison']['history_max_event_date_before']<date for side in ('a','b'))
            # A completed prediction already owns its comparison. The secondary
            # button must navigate to it without starting another worker or
            # creating a statistics-only history entry.
            from analyzer_reporting import report_sections
            previous_job=app.controller.job_id;previous_history=len(app.history.entries())
            previous_displayed=app.result;previous_report=app.result_text;previous_metrics=report_sections(payload)
            comparison_started=time.monotonic();app.compare();window.update()
            comparison_navigation_seconds=round(time.monotonic()-comparison_started,4)
            assert not app.controller.busy and app.controller.job_id==previous_job
            assert app.notebook.select()==str(app.comparison)
            assert app.result is previous_displayed and app.result_text==previous_report
            assert report_sections(app.result)==previous_metrics
            assert len(app.history.entries())==previous_history
            assert 'No datasets reloaded' in app.status.get()
            if label=='forward':
                forward=payload
                if args.baseline:
                    baseline=json.loads(args.baseline.read_text(encoding='utf-8'))
                    assert abs(payload['fighter_a_win_probability']-baseline['fighter_a_win_probability'])<1e-12
                if args.screenshots:
                    # Explicitly add the test-tool directory, after all packaged
                    # application imports, to import our screenshot helper only.
                    sys.path.append(str(Path(__file__).resolve().parent))
                    from capture_window import capture
                    capture(window,args.screenshots/(sex+'.png'))
                    app.notebook.select(app.comparison);window.update()
                    capture(window,args.screenshots/(sex+'-comparison.png'))
                    app.notebook.select(app.notebook.tabs()[2]);window.update()
                    capture(window,args.screenshots/(sex+'-full-report.png'))
                    app.output.yview_moveto(0)
                    app.notebook.select(app.overview)
            elif label=='reverse':assert abs(payload['fighter_a_win_probability']-forward['fighter_b_win_probability'])<1e-12
            elif label=='single-worker':assert abs(payload['fighter_a_win_probability']-forward['fighter_a_win_probability'])<1e-12
            elif label=='historical':
                if sex=='men':assert payload['actual_max_training_event_date_used']<date and payload['excluded_rows_on_or_after_fight_date']>0
                else:
                    path=ROOT/'womens_ufc_model/output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'
                    with path.open(encoding='utf-8-sig',newline='') as stream:
                        rows=[r for r in csv.DictReader(stream) if r['fighter_a_won'] in ('0','1','0.0','1.0') and r['fight_id'] and r['event_date']<date]
                    assert payload['training_rows_used']==len(rows)
            # Clipboard and export must retain the completed matchup after editing.
            expected=app.result_text;app.names['a'].set('Changed input');app.copy();window.update()
            assert window.clipboard_get()==expected
            saved=args.out.parent/result_filename(payload)
            gui.filedialog.asksaveasfilename=lambda **kw:str(saved)
            app.save();assert saved.read_text(encoding='utf-8')==expected
            atomic_json(args.out.parent/(sex+'-'+label+'.json'),payload)
            report['runs'].append(dict(case=label,**timing,probability=payload['fighter_a_win_probability'],engine_seconds=payload['elapsed_seconds'],first_comparison_seconds=payload.get('time_to_comparison_seconds'),comparison_navigation_seconds=comparison_navigation_seconds,comparison_navigation='PASS: no worker, unchanged report/metrics/history',stage_timings_seconds=payload.get('stage_timings_seconds'),render_seconds=round(app.last_render_seconds,3),peak_working_set_mib=payload['peak_process_tree_working_set_mib'],model=payload['model_version'],report_lines=len(expected.splitlines()),comparison_rows=sum(' | ' in line for line in expected.splitlines()),copy_and_save='PASS'))
            atomic_json(args.out,dict(report,status='RUNNING'))
        report['status']='PASS';atomic_json(args.out,report)
    finally:
        if app.controller.busy:app.controller.terminate()
        app.destroy()

if __name__=='__main__':main()

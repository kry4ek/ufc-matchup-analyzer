"""UFC Matchup Analyzer: a small public interface over the retained engines."""
from __future__ import annotations
import argparse, csv, datetime as dt, difflib, json, math, os, pathlib, re, subprocess, sys, tempfile, time, unicodedata
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from analyzer_support import ROOT, VERSION, atomic_json, data_health, doctor
from analyzer_catalog import FighterCatalog, iso_date, key, resolve_fighter, validate_matchup
from analyzer_runtime import Cancelled, ProcessTree, check_cancel, operation_lock, python_executable, subprocess_options, runtime_environment
from analyzer_results import format_result

def validate_prediction(payload):
    a=float(payload['fighter_a_win_probability']);b=float(payload['fighter_b_win_probability'])
    if not all(math.isfinite(x) and 0<=x<=1 for x in (a,b)) or abs(a+b-1)>1e-8:raise ValueError('Engine returned invalid probabilities')
    if payload['predicted_winner'] not in (payload['fighter_a'],payload['fighter_b']):raise ValueError('Engine returned an invalid winner')
    if payload.get('training_rows',payload.get('training_rows_used',0))<=0:raise ValueError('Engine did not train on usable rows')
    return payload

def process_peak_mib(pid):
    if os.name!='nt':return None
    import ctypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    class ProcessEntry(ctypes.Structure):
        _fields_=[('dwSize',ctypes.c_ulong),('cntUsage',ctypes.c_ulong),('th32ProcessID',ctypes.c_ulong),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',ctypes.c_ulong),('cntThreads',ctypes.c_ulong),('th32ParentProcessID',ctypes.c_ulong),('pcPriClassBase',ctypes.c_long),('dwFlags',ctypes.c_ulong),('szExeFile',ctypes.c_wchar*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.CreateToolhelp32Snapshot.restype=ctypes.c_void_p
    snapshot=kernel.CreateToolhelp32Snapshot(2,0);parents={};ids={pid}
    if snapshot and snapshot!=ctypes.c_void_p(-1).value:
        try:
            entry=ProcessEntry();entry.dwSize=ctypes.sizeof(entry)
            present=kernel.Process32FirstW(ctypes.c_void_p(snapshot),ctypes.byref(entry))
            while present:
                parents[entry.th32ProcessID]=entry.th32ParentProcessID
                present=kernel.Process32NextW(ctypes.c_void_p(snapshot),ctypes.byref(entry))
        finally:kernel.CloseHandle(ctypes.c_void_p(snapshot))
    while True:
        children={child for child,parent in parents.items() if parent in ids}
        if children<=ids:break
        ids.update(children)
    total=0
    for child in ids:
        handle=kernel.OpenProcess(0x410,False,child)
        if not handle:continue
        try:
            counters=Counters();counters.cb=ctypes.sizeof(counters)
            if kernel.K32GetProcessMemoryInfo(ctypes.c_void_p(handle),ctypes.byref(counters),counters.cb):total+=counters.WorkingSetSize
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    return total/1048576 if total else None

class PredictionFailure(RuntimeError):
    def __init__(self, message, log, worker_permission=False):
        super().__init__(message)
        self.log = str(log)
        self.worker_permission = worker_permission

def predict(args,root=ROOT,progress=None,cancel=None):
    with operation_lock(root, 'prediction'):
        return _predict(args,root,progress,cancel)

def _predict(args,root=ROOT,progress=None,cancel=None):
    root=pathlib.Path(root);sex=args.sex
    operation=getattr(args,'command','predict')
    started_operation=time.monotonic()
    from analyzer_history import History, calculation_context, history_enabled, utc_now
    emit=progress or (lambda **event: None)
    check_cancel(cancel)
    emit(stage='checking',message='Checking datasets and fighter names')
    if args.as_of_date and (args.as_of_date>=args.fight_date or args.as_of_date>dt.date.today().isoformat()):raise ValueError('--as-of-date must be before fight-date and no later than today')
    if (root/'.runtime/maintenance.lock').exists():raise RuntimeError('Data maintenance is active or interrupted. Run doctor before predicting.')
    checks=data_health(root,True,(sex,))
    validation_seconds=time.monotonic()-started_operation
    bad=[x for x in checks if x['status']=='FAIL']
    if bad:raise ValueError('Required data is not ready: '+bad[0]['path']+'; '+bad[0].get('message',''))
    a,aid=resolve_fighter(args.fighter_a,sex,root,args.fighter_a_id,args.profiles)
    b,bid=resolve_fighter(args.fighter_b,sex,root,args.fighter_b_id,args.profiles)
    if key(a)==key(b) and aid==bid:raise ValueError('Choose two different fighters')
    match=validate_matchup(sex,args.division,args.fight_date,(a,aid),(b,bid))
    cutoff=args.as_of_date or ((dt.date.fromisoformat(args.fight_date)-dt.timedelta(days=1)).isoformat() if args.fight_date<=dt.date.today().isoformat() else dt.date.today().isoformat()) if sex=='men' else args.fight_date
    canonical=dict(operation=operation,sex=sex,fighter_a=a,fighter_b=b,fighter_a_id=aid,fighter_b_id=bid,division=match,fight_date=args.fight_date,effective_cutoff=cutoff,as_of_date=args.as_of_date,workers=args.workers or 'automatic')
    if args.profiles:
        from analyzer_support import digest
        canonical['profiles_sha256']=digest(args.profiles)
    context=calculation_context(root,sex,checks)
    history=History(root)
    if getattr(args,'use_cache',False) and not getattr(args,'force_recalculate',False) and history_enabled(root):
        try:
            entry=history.lookup(canonical,context)
            if entry:
                payload=dict(entry['payload'],reused=True,history_id=entry['id'],reuse_seconds=round(time.monotonic()-started_operation,3))
                if operation=='predict':validate_prediction(payload)
                if args.out:atomic_json(pathlib.Path(args.out).resolve(),payload)
                print(format_result(payload))
                emit(stage='complete',message='Opened matching saved analysis',cancellable=False)
                return payload
        except (OSError,ValueError,KeyError) as exc:
            print('Saved result could not be reused: '+str(exc))
    catalog=FighterCatalog(sex,root)
    coverage={side:catalog.coverage(identity,args.fight_date,match) for side,identity in [('a',(a,aid)),('b',(b,bid))]}
    coverage_warnings=[]
    for side,name in [('a',a),('b',b)]:
        info=coverage[side]
        if not info['fights']:coverage_warnings.append(name+': no eligible UFC history before the fight date.')
        elif info['fights']<5:coverage_warnings.append(name+': limited recorded history ('+str(info['fights'])+' eligible UFC fights).')
        if not info['division_fights']:coverage_warnings.append(name+': no recorded history in the selected division before the fight date.')
    directory=root/('mens_ufc_model' if sex=='men' else 'womens_ufc_model')
    runtime=root/'.runtime/predictions';runtime.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    activity='Preparing statistics' if operation=='compare' else 'Analyzing'
    print(f'{activity}: {a} vs {b}. Computing locally; allow a few minutes …',flush=True)
    with tempfile.TemporaryDirectory(prefix='prediction-',dir=runtime) as tmp:
        temp=pathlib.Path(tmp);out=temp/'result.json';log=temp/'engine.log';events=temp/'engine-events.jsonl'
        command=[python_executable(),str(root/'analyzer_engine_runner.py'),sex,operation,'--fighter-a',a,'--fighter-b',b,'--fight-date',args.fight_date]
        if sex=='men':
            command+=['--weight-class',match,'--model-version','v3_bayes_smoothed','--out',str(out)]
            cutoff=args.as_of_date
            if not cutoff and args.fight_date<=dt.date.today().isoformat():cutoff=(dt.date.fromisoformat(args.fight_date)-dt.timedelta(days=1)).isoformat()
            if cutoff:command+=['--as-of-date',cutoff,'--allow-future-training-rows']
            if aid:command+=['--fighter-a-id',aid]
            if bid:command+=['--fighter-b-id',bid]
            if args.profiles:
                with pathlib.Path(args.profiles).open(encoding='utf-8-sig',newline='') as f:profiles=list(csv.DictReader(f))
                for label,name in [('a',a),('b',b)]:
                    row=next((x for x in profiles if key(x.get('fighter',x.get('fighter_name','')))==key(name)),{})
                    for col in ['height_cm','reach_cm','stance','date_of_birth']:
                        if row.get(col):command+=['--fighter-'+label+'-'+col.replace('_','-'),row[col]]
        else:
            if args.as_of_date:raise ValueError('--as-of-date is available for men; women always use event_date < fight-date.')
            command+=['--division',"Women's "+match,'--json-out',str(out),'--profiles',str(pathlib.Path(args.profiles).resolve() if args.profiles else directory/'output_quality_fixed/ufc_womens_fighter_profiles.csv')]
            if args.profiles:command+=['--allow-manual-profile-fallback']
        env=runtime_environment(root)
        env['UFC_ENGINE_EVENTS']=str(events)
        if args.workers==1:env['LOKY_MAX_CPU_COUNT']='1'
        emit(stage='loading',message='Loading the selected model and preparing fighter statistics',cancellable=True)
        check_cancel(cancel)
        with log.open('w',encoding='utf-8') as stream:
            process=subprocess.Popen(command,cwd=directory,env=env,stdout=stream,stderr=subprocess.STDOUT,**subprocess_options())
            tree=ProcessTree(process)
            peak=0.0;next_progress=30;next_sample=0
            event_offset=0
            def drain_events():
                nonlocal event_offset
                if not events.exists():return
                with events.open('rb') as source:
                    source.seek(event_offset);raw=source.read()
                for line in raw.splitlines(keepends=True):
                    if not line.endswith(b'\n'):break
                    event_offset+=len(line);event=json.loads(line)
                    kind=event.pop('type')
                    if kind=='comparison_ready':
                        preview=event['payload'];preview.update(coverage=coverage,coverage_warnings=coverage_warnings,fighter_a_id=aid,fighter_b_id=bid,analyzer_version=VERSION,generated_at=utc_now(),result_state='pending' if operation=='predict' else 'comparison')
                        emit(event_type=kind,**event)
                    else:emit(**event)
            try:
                while True:
                    check_cancel(cancel)
                    drain_events()
                    if time.monotonic()-start>=next_sample:
                        peak=max(peak,process_peak_mib(process.pid) or 0);next_sample+=5
                    try:code=process.wait(timeout=.2);drain_events();break
                    except subprocess.TimeoutExpired:
                        if time.monotonic()-start>=next_progress:
                            print(f'Still computing ({time.monotonic()-start:.0f}s) …',flush=True);next_progress+=30
            except BaseException:
                tree.terminate();raise
            finally:tree.close()
        diagnostic=log.read_text(encoding='utf-8',errors='replace')
        if code or not out.exists():
            if args.verbose:print(diagnostic)
            path=runtime/'last_failure.log';path.write_text(diagnostic,encoding='utf-8')
            worker_permission=bool(re.search(r'(PermissionError|WinError 5|Access is denied)',diagnostic,re.I) and re.search(r'(loky|joblib|SemLock|multiprocessing)',diagnostic,re.I))
            raise PredictionFailure(f'Analysis could not finish. Open the diagnostic log for details.',path,worker_permission)
        payload=json.loads(out.read_text(encoding='utf-8'))
        if sex=='men' and operation=='predict':
            payload['fighter_a_win_probability']=payload['fighter_a_final_probability'];payload['fighter_b_win_probability']=payload['fighter_b_final_probability']
        elif sex=='women':
            payload['model_version']='v1_current_ensemble'
            training=directory/'output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv'
            with training.open(encoding='utf-8-sig',newline='') as stream:
                payload['actual_max_training_event_date_used']=max((row['event_date'] for row in csv.DictReader(stream) if row.get('fighter_a_won') in ('0','1','0.0','1.0') and row.get('fight_id') and row['event_date']<args.fight_date),default=None)
        payload.setdefault('division',("Women's " if sex=='women' else '')+match)
        payload.setdefault('fight_date',args.fight_date)
        payload['analyzer_version']=VERSION;payload['elapsed_seconds']=round(time.monotonic()-start,2)
        payload.update(result_state='comparison' if operation=='compare' else 'complete',coverage=coverage,coverage_warnings=coverage_warnings,fighter_a_id=aid,fighter_b_id=bid,generated_at=utc_now(),reused=False,calculation_request=canonical,calculation_fingerprint=__import__('analyzer_history').fingerprint(context))
        payload.setdefault('stage_timings_seconds',{})['validation']=round(validation_seconds,3)
        payload['worker_mode']='single' if args.workers==1 else 'automatic'
        payload['peak_process_tree_working_set_mib']=round(peak,1) if peak else None
        payload['memory_measurement_scope']='engine and descendant processes; sampled sum of working sets; shared pages may be counted more than once'
        if operation=='predict':validate_prediction(payload)
        if history_enabled(root):
            try:payload['history_id']=history.save(canonical,context,payload)
            except (OSError,ValueError) as exc:payload['history_notice']='Analysis completed, but local history could not be saved: '+str(exc)
        emit(stage='complete',message='Analysis complete',cancellable=False)
        print(format_result(payload))
        if args.verbose:print(diagnostic)
        if args.out:atomic_json(pathlib.Path(args.out).resolve(),payload);print('Saved JSON: '+str(pathlib.Path(args.out).resolve()))
        return payload

def parser():
    p=argparse.ArgumentParser(description='UFC Matchup Analyzer — local men’s and women’s matchup analysis.')
    p.add_argument('--version',action='version',version=VERSION);sub=p.add_subparsers(dest='command')
    for operation in ('predict','compare'):
        q=sub.add_parser(operation,help='Analyze a matchup' if operation=='predict' else 'Compare dated statistics without fitting prediction models');q.add_argument('sex',choices=['men','women'])
        for name in ['fighter-a','fighter-b','division']:q.add_argument('--'+name,required=True)
        q.add_argument('--fight-date',required=True,type=iso_date);q.add_argument('--as-of-date',type=iso_date)
        q.add_argument('--fighter-a-id');q.add_argument('--fighter-b-id');q.add_argument('--profiles',type=pathlib.Path);q.add_argument('--out',type=pathlib.Path)
        q.add_argument('--workers',type=int,choices=[1],default=None,help='Use one worker; omit for normal parallel execution');q.add_argument('--verbose',action='store_true')
        cache=q.add_mutually_exclusive_group();cache.add_argument('--use-cache',action='store_true');cache.add_argument('--force-recalculate',action='store_true')
    q=sub.add_parser('doctor',help='Check installation and data');q.add_argument('--skip-hashes',action='store_true',help='Faster schema check; does not verify checksums')
    for name in ['update','rebuild']:
        q=sub.add_parser(name,help='Safely '+name+' datasets');q.add_argument('--target',choices=['men','women','all'],default='all')
        if name=='update':q.add_argument('--apply',action='store_true');q.add_argument('--max-events',type=int);q.add_argument('--from-date',type=iso_date)
    q=sub.add_parser('recover',help='Restore data from a failed or latest committed transaction');q.add_argument('--transaction')
    return p

def interactive():
    print('UFC Matchup Analyzer\n1. Analyze a matchup\n2. Check installation\n3. Preview data update\n4. Apply data update\n5. Rebuild local features\n6. Exit')
    choice=input('Choose 1–6: ').strip()
    if choice=='1':
        sex=input('Model (men/women): ').strip().lower()
        values=['predict',sex,'--fighter-a',input('Fighter A: ').strip(),'--fighter-b',input('Fighter B: ').strip(),'--division',input('Division (for example Lightweight or Flyweight): ').strip(),'--fight-date',input('Fight date (YYYY-MM-DD): ').strip()]
        if input('Use one worker for compatibility? [Y/n]: ').strip().lower()!='n':values+=['--workers','1']
        return values
    if choice=='2':return ['doctor']
    if choice in ('3','4','5'):
        target=input('Target (men/women/all) [all]: ').strip() or 'all';values=['rebuild' if choice=='5' else 'update','--target',target]
        if choice=='4':
            if input('Apply changes after staged validation? [y/N]: ').strip().lower()!='y':return ['doctor']
            values+=['--apply']
        return values
    if choice=='6':return None
    raise ValueError('Choose a number from 1 to 6.')

def main(argv=None):
    argv=sys.argv[1:] if argv is None else argv
    try:
        if not argv:
            if not sys.stdin.isatty():parser().print_help();return 0
            argv=interactive()
            if argv is None:return 0
        args=parser().parse_args(argv)
        if args.command=='doctor':
            with operation_lock(ROOT,'doctor'):return doctor(skip_hashes=args.skip_hashes)
        if args.command in ('predict','compare'):predict(args);return 0
        from analyzer_maintenance import maintenance,recover
        if args.command=='recover':recover(transaction=args.transaction);return 0
        if args.command in ('update','rebuild'):
            if getattr(args,'max_events',None) is not None and args.max_events<1:raise ValueError('--max-events must be positive')
            maintenance(kind=args.command,target=args.target,apply=getattr(args,'apply',False),max_events=getattr(args,'max_events',None),from_date=getattr(args,'from_date',None));return 0
        parser().print_help();return 0
    except (ValueError,RuntimeError,OSError,subprocess.SubprocessError) as exc:print('ERROR: '+str(exc),file=sys.stderr);return 1
    except (KeyboardInterrupt,EOFError):print('\nStopped. Use doctor if data maintenance was interrupted.',file=sys.stderr);return 130

if __name__=='__main__':raise SystemExit(main())

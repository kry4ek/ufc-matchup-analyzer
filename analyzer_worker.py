"""JSON-lines worker protocol. No GUI behavior depends on console text."""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import importlib
import json
import os
from pathlib import Path
import sys
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parent))

from analyzer_support import ROOT, VERSION, data_health, dependency_health, atomic_json
from analyzer_catalog import FighterCatalog
from analyzer_history import calculation_context, fingerprint, utc_now
from analyzer_runtime import Cancelled, check_cancel, operation_lock

def installation_report(root=ROOT):
    checks=dependency_health(root)
    checks.extend(data_health(root))
    checks.append(dict(component='Python',status='PASS' if sys.version_info[:3]==(3,14,7) and sys.maxsize>2**32 else 'FAIL',message=sys.version.split()[0]+'; portable build requires Python 3.14.7 x64'))
    for name in ('numpy','pandas','sklearn','joblib','requests','bs4','lxml.etree'):
        try:importlib.import_module(name)
        except (ImportError,OSError) as exc:checks.append(dict(component=name,status='FAIL',message=str(exc)))
    dates={}
    for sex in ('men','women'):
        prefix='mens_ufc_model/' if sex=='men' else 'womens_ufc_model/'
        dates[sex]=max((c.get('latest_date') or '' for c in checks if c.get('path','').startswith(prefix)),default='') or 'Unknown'
    ready=all(c['status']=='PASS' for c in checks)
    report=dict(ready=ready,checks=checks,dates=dates,version=VERSION)
    if ready:
        report['catalogs']={sex:FighterCatalog(sex,root).to_payload() for sex in ('men','women')}
        report['calculation_fingerprints']={sex:fingerprint(calculation_context(root,sex,[c for c in checks if c.get('path','').startswith('mens_ufc_model/' if sex=='men' else 'womens_ufc_model/')])) for sex in ('men','women')}
    state=Path(root)/'.runtime/local_dataset_state.json'
    report['backup_available']=False
    if state.exists():
        try:
            transaction=json.loads(state.read_text()).get('transaction','')
            journal=Path(root)/'.runtime/transactions'/transaction/'journal.json'
            report['backup_available']=journal.exists() and json.loads(journal.read_text()).get('status')=='committed' and (journal.parent/'before').exists()
        except (OSError,ValueError):pass
    try:report['maintenance_status']=json.loads((Path(root)/'.runtime/maintenance_status.json').read_text())
    except (OSError,ValueError):report['maintenance_status']={}
    return report

def execute(request,emit,cancel=None,root=ROOT):
    from analyzer_maintenance import cleanup_history,maintenance,recover,recover_interrupted
    from ufc_matchup_analyzer import parser,predict
    root=Path(root)
    operation=request['operation']
    with operation_lock(root,operation):
        if operation in ('startup','doctor'):
            emit(stage='checking',message='Checking installation and dataset integrity',cancellable=False)
            recovered=recover_interrupted(root)
            report=installation_report(root)
            report['recovered']=recovered
            if report['ready']:cleanup_history(root)
            else:print(json.dumps(report,indent=2,ensure_ascii=False))
            return report
        if operation in ('predict','compare'):
            argv=[operation,request['sex'],'--fighter-a',request['fighter_a'],'--fighter-b',request['fighter_b'],'--division',request['division'],'--fight-date',request['fight_date']]
            for field in ('fighter_a_id','fighter_b_id','workers','as_of_date'):
                if request.get(field):argv.extend(['--'+field.replace('_','-'),str(request[field])])
            args=parser().parse_args(argv)
            args.use_cache=request.get('use_cache',True);args.force_recalculate=request.get('force_recalculate',False)
            return predict(args,root,emit,cancel)
        if operation in ('update','rebuild'):
            transaction=maintenance(root,kind=operation,target='all',apply=True,max_events=request.get('max_events'),from_date=request.get('from_date'),progress=emit,cancel=cancel)
            journal=json.loads((root/'.runtime/transactions'/transaction/'journal.json').read_text(encoding='utf-8'))
            report=installation_report(root)
            report.update(transaction=transaction,status=journal['status'],summary=journal['summary'])
            status=dict(report.get('maintenance_status') or {})
            if operation=='update':status['last_successful_check']=utc_now()
            if journal['status']=='committed':
                from analyzer_support import digest
                changed=any((root/r['path']).exists() and (not r['existed'] or digest(root/r['path'])!=digest(root/'.runtime/transactions'/transaction/'before'/r['path'])) for r in journal['promotions'] if r['path'].endswith('.csv'))
                if changed:status['last_successful_change']=utc_now()
            status['last_operation']=operation;status['summary']=journal['summary'];status['stages']='Staging → audit → rebuild → validate → install'
            atomic_json(root/'.runtime/maintenance_status.json',status);report['maintenance_status']=status
            cleanup_history(root)
            return report
        if operation=='recover':
            state=root/'.runtime/local_dataset_state.json'
            if not state.exists():raise ValueError('There is no previous dataset update to restore.')
            transaction=json.loads(state.read_text(encoding='utf-8')).get('transaction')
            check_cancel(cancel)
            emit(stage='committing',message='Restoring the previous datasets',cancellable=False)
            recover(root,transaction)
            report=installation_report(root)
            status=report.get('maintenance_status',{})
            status.update(last_successful_change=utc_now(),last_operation='restore',stages='Restore → verify',summary={})
            atomic_json(root/'.runtime/maintenance_status.json',status)
            report['maintenance_status']=status
            return report
        raise ValueError('Unsupported operation.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--events',type=Path,required=True);p.add_argument('--cancel',type=Path,required=True);args=p.parse_args()
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    request=json.loads(args.request.read_text(encoding='utf-8'))
    log=ROOT/'.runtime/logs'/ (args.request.stem+'.log');log.parent.mkdir(parents=True,exist_ok=True)
    args.events.parent.mkdir(parents=True,exist_ok=True)
    with args.events.open('w',encoding='utf-8',buffering=1) as events,log.open('w',encoding='utf-8') as stream:
        def send(kind,**payload):
            events.write(json.dumps(dict(type=kind,job_id=request.get('job_id'),request_fingerprint=request.get('request_fingerprint'),**payload),ensure_ascii=False,allow_nan=False)+'\n');events.flush()
        def progress(**payload):send(payload.pop('event_type','progress'),**payload)
        try:
            with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
                result=execute(request,progress,args.cancel.exists)
            send('result',operation=request['operation'],payload=result)
            return 0
        except BaseException as exc:
            traceback.print_exc(file=stream)
            stream.flush()
            send('error',code='cancelled' if isinstance(exc,Cancelled) else 'worker_permission' if getattr(exc,'worker_permission',False) else 'failed',message=str(exc) or type(exc).__name__,log=getattr(exc,'log',str(log)))
            return 130 if isinstance(exc,Cancelled) else 1

if __name__=='__main__':raise SystemExit(main())
